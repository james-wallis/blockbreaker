# blockbreaker.py - web/Pyodide port of the original first-year game.
#
# The game LOGIC is unchanged from blockbreaker.py in the repo root. The only
# differences required to run in a browser are:
#   * the blocking game loop is now async: time.sleep -> await asyncio.sleep,
#     win.getMouse() -> await win.getMouse(), and the loop yields each frame so
#     the browser stays responsive.
#   * high scores are saved to a shared online leaderboard (Turso, via the
#     /api/scores serverless function) instead of a text file, with browser
#     localStorage kept as an offline fallback cache.
# Rendering/input is handled by the canvas-backed graphics.py shim in this folder.

from graphics import *
import asyncio
import json
import timeit
import math
import random
from js import localStorage
from pyodide.http import pyfetch

# constants
wallThickness = 1
batWidth = 15
batX = 50
batThickness = 1
ballRadius = 1
blockWidth = 6
blockHeight = 2
colourList = ["Red", "Orange", "Yellow", "Green", "Blue"]
initialBallSpeedX = -0.1
initialBallSpeedY = 1
directionSpeedChangeX = 1
# Seconds per game-loop iteration. Lower = faster game. Tune to taste.
FRAME_DELAY = 0.016

# High-score persistence.
#
# Scores live in a shared Turso database, reached through the /api/scores
# serverless function, so every visitor shares one global leaderboard.
# localStorage is kept as an offline fallback/cache so the game still works if
# the API is unreachable (e.g. served from a plain static server with no backend).
API_URL = "/api/scores"
SCORE_KEY = "blockbreaker_highscores"
DEFAULT_SCORES = "King Henry,50\nJimBob,100\nAverage Joe,10\n"


def _load_local_raw():
    data = localStorage.getItem(SCORE_KEY)
    if data is None:
        localStorage.setItem(SCORE_KEY, DEFAULT_SCORES)
        return DEFAULT_SCORES
    return data


def _local_scores_lists():
    # Parse the localStorage cache into [[name, scoreStr], ...]
    highScoresList = []
    raw = _load_local_raw()
    for line in raw.split("\n"):
        line = line.rstrip("\r").strip()
        if not line:
            continue
        highScoresList.append(line.split(","))
    return highScoresList


def _local_write(name, score):
    raw = _load_local_raw()
    if raw and not raw.endswith("\n"):
        raw += "\n"
    raw += "{0},{1}\n".format(name, score)
    localStorage.setItem(SCORE_KEY, raw)


async def _fetch_remote_scores():
    """Top scores from the shared API as [[name, scoreStr], ...], or None on failure."""
    try:
        resp = await pyfetch(API_URL, method="GET")
        if resp.status != 200:
            return None
        data = await resp.json()
        return [[str(row["name"]), str(int(row["score"]))] for row in data["scores"]]
    except Exception:
        return None


async def _post_remote_score(name, score):
    try:
        await pyfetch(
            API_URL,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"name": name, "score": score}),
        )
        return True
    except Exception:
        return False


# main and submain exist because when the game restarts, I want to use the same graphWindow
async def main():
    court = makeCourt()
    try:
        await subMain(court)
    except SystemExit:
        pass


async def subMain(court):
    bat = makeBat(court)
    blockList = makeBlocks(court)
    dividerList = await instructions(court)
    scoreList, numberOfScoreList, timer, totalScore, stopButton, \
        informationBarList, colourScoreList, level, levelNo = informationBar(court)
    ball = makeBall(court)
    superList = [informationBarList, colourScoreList, numberOfScoreList, ball, bat]
    await playGame(court, bat, ball, blockList, dividerList, scoreList,
                   numberOfScoreList, timer, totalScore, stopButton, superList, level, levelNo)


# Setting up the game
def makeCourt():
    win = GraphWin("Block Breaker", 900, 600)
    win.setCoords(0, 0, 140, 100)
    win.setBackground("black")
    drawRectangle(win, Point(0, 100), Point(100, 100 - wallThickness), "white")
    drawRectangle(win, Point(0, wallThickness), Point(wallThickness, 100 - wallThickness), "white")
    drawRectangle(win, Point(100, wallThickness), Point(100 - wallThickness, 100 - wallThickness), "white")
    return win


def makeBat(win):
    bat = drawRectangle(win,
                        Point(batX - batWidth / 2, 4 + batThickness),
                        Point(batX + batWidth / 2, 4 - batThickness),
                        "white")
    return bat


def makeBall(win):
    ball = drawCircle(win, Point(50, 10), ballRadius, "white")
    return ball


def makeBlocks(win):
    blockList = []
    for column in range(10):
        moveY = column * 3
        for row in range(13):
            moveX = row * 7
            # Picks the colour out of the colour list, changes every two rows
            colour = colourList[column // 2]
            # Enable me to move the blocks around
            blockX = 8 + moveX
            blockY = 94 - moveY
            block = drawRectangle(win, Point(blockX - blockWidth / 2, blockY + blockHeight / 2),
                                  Point(blockX + blockWidth / 2, blockY - blockHeight / 2), colour)
            blockCentre = block.getCenter()
            # Adds the blocks to a list to enable me to get rid of them when hit
            blockList.append([block, colour, int(block.getP1().getX()), int(block.getP1().getY()),
                              int(block.getP2().getX()), int(block.getP2().getY())])
    return blockList


# Tells the player what to do and gives a countdown until the game begins
async def instructions(win):
    title = drawText(win, Point(50, 60), "Block Breaker", 24)
    await asyncio.sleep(1)
    instruction = drawText(win, Point(50, 54), "Instructions", 16)
    pointerNote = drawText(win, Point(50, 10), "(Now works with pointer drag)", 12)
    message = drawText(win, Point(50, 42), " To move the bat left,\n     click on the left hand side of the window.\
    \n To move the bat right, \n   click on the right hand side of the window. \
    \nNote: Bat will not move if clicked in the stats section", 14)
    # Creates the divider which stays throughout game to remind the player where they should click to move the bat
    dividerColour = color_rgb(38, 38, 38)
    dividerLine = Line(Point(50, 33), Point(50, 22))
    dividerLine.setOutline(dividerColour), dividerLine.draw(win)
    dividerTextLeft = drawText(win, Point(40, 27), "Left", 12)
    dividerTextRight = drawText(win, Point(60, 27), "Right", 12)
    countDown = 5
    startTime = drawText(win, Point(50, 20), "Game will start in " + str(countDown), 14)
    await asyncio.sleep(1)
    # Starts the countdown
    for i in range(countDown):
        startTime.setText("Game will start in {0}".format(countDown - i))
        await asyncio.sleep(1)
    title.undraw()
    instruction.undraw()
    pointerNote.undraw()
    message.undraw()
    startTime.undraw()
    # Divider is put in a list to remove of window later
    dividerList = [dividerLine, dividerTextLeft, dividerTextRight]
    return dividerList


# The information bar is the right side of the window
def informationBar(win):
    # Displays title
    title = drawText(win, Point(120, 90), "Block Breaker", 20)
    author = drawText(win, Point(120, 86), "By James Wallis", 10)
    # Displays in game stats table
    inGameStats = drawText(win, Point(115, 70), "In Game Stats", 14)
    horizontalLine = Line(Point(103, 68), Point(137, 68))
    horizontalLine.setOutline("white"), horizontalLine.draw(win)
    verticalLine = Line(Point(127, 72), Point(127, 39))
    verticalLine.setOutline("white"), verticalLine.draw(win)
    # Displays the name for the colour scoring system
    colourScoreList = []
    for colourNumber in range(5):
        moveText = colourNumber * 3
        colourScore = drawText(win, Point(118, 55 - moveText), colourList[colourNumber], 12)
        colourScoreList.append(colourScore)
    # Creates the scoring variables
    score, blueScore, greenScore, yellowScore, orangeScore, redScore = 0, 0, 0, 0, 0, 0
    # Creates a list to easily transport the scores around the program
    scoreList = [score, blueScore, greenScore, yellowScore, orangeScore, redScore]
    numberOfScoreList = []
    # Displays the score number next to the correct colour name
    for scoreNumber in range(5):
        moveText = scoreNumber * 3
        scoreScore = drawText(win, Point(133, 55 - moveText), scoreList[scoreNumber + 1], 12)
        # Uses a list to transport the different texts that display the current scores
        numberOfScoreList.append(scoreScore)
    totalScoreText = drawText(win, Point(115, 60), "Total Score:", 14)
    totalScore = drawText(win, Point(133, 60), "0", 14)
    # Sets up the timer
    timerTitle = drawText(win, Point(115, 65), "Time Played:", 14)
    timer = drawText(win, Point(133, 65), "0", 14)
    # Sets up the level notation, starting at 1
    level = 1
    levelNo = drawText(win, Point(133, 30), level, 14)
    levelText = drawText(win, Point(115, 30), "Current Level:", 14)
    stopButton = drawRectangle(win, Point(110, 15), Point(130, 10), "red4")
    stopButton.setOutline("white")
    stopButtonText = drawText(win, Point(120, 12.5), "End Game", 14)
    # List is created to edit/remove items when the game is restarted
    informationBarList = [title, author, inGameStats, horizontalLine, verticalLine,
                          totalScoreText, totalScore, timerTitle, timer, stopButton,
                          stopButtonText, levelNo, levelText]
    return scoreList, numberOfScoreList, timer, totalScore, \
        stopButton, informationBarList, colourScoreList, level, levelNo


# Used for rectangles
def drawRectangle(win, point1, point2, colour):
    rectangle = Rectangle(point1, point2)
    rectangle.setFill(colour)
    rectangle.setOutline(colour)
    rectangle.draw(win)
    return rectangle


# Used for circles
def drawCircle(win, centre, radius, colour):
    circle = Circle(centre, radius)
    circle.setFill(colour)
    circle.setOutline(colour)
    circle.draw(win)
    return circle


# Used to drawText
def drawText(win, centre, string, size):
    text = Text(centre, string)
    text.setFill("white")
    text.setSize(size)
    text.setFace("courier")
    text.draw(win)
    return text


# Section 2: While the game is playing
# Making the game Function
async def playGame(court, bat, ball, blockList, dividerList, scoreList,
                   numberOfScoreList, timer, totalScore, stopButton, superList, level, levelNo):
    ballSpeedX = initialBallSpeedX
    ballSpeedY = initialBallSpeedY
    gameOver = False
    # start and oldTime make the timer function
    start = timeit.default_timer()
    oldTime = 0
    # Apply any level-based block styling for the starting level up front.
    recolourBlocks(blockList, level)
    while not gameOver:
        ballSpeedX, ballSpeedY = checkWall(ball, ballSpeedX, ballSpeedY)
        scoreList, ballSpeedX, ballSpeedY, level = await checkBlocks(ball, ballSpeedX,
                                                                     ballSpeedY, blockList, scoreList, court, numberOfScoreList,
                                                                     totalScore, level, levelNo)
        ballSpeedX, ballSpeedY = checkBat(bat, ball, ballSpeedX, ballSpeedY)
        click = moveBat(court, bat)
        ball.move(ballSpeedX, ballSpeedY)
        # Set the in game timer
        newTime = math.ceil(timeit.default_timer() - start)
        # The if statement was included so the timer would only change when the number was different to oldtime
        # Allowing it to do it automatically slowed the game down
        if newTime > oldTime:
            oldTime = setTimer(timer, start, newTime, oldTime)
        gameOver = checkGameOver(ball, blockList, court, click, stopButton)
        # Yield to the browser so the page stays responsive and renders a frame.
        await asyncio.sleep(FRAME_DELAY)
    await gameEnded(court, scoreList, dividerList, start, superList, blockList, newTime)


# Makes the direction of the ball change when a wall is hit
def checkWall(ball, ballSpeedX, ballSpeedY):
    centre = ball.getCenter()
    if centre.getY() + ballRadius >= 100 - wallThickness:
        ballSpeedY = -ballSpeedY
    if centre.getX() - ballRadius < wallThickness or centre.getX() + ballRadius > 100 - wallThickness:
        ballSpeedX = -ballSpeedX
    return ballSpeedX, ballSpeedY


# Enables rectangles/blocks at the top of the window to be hit, deleted and scored
async def checkBlocks(ball, ballSpeedX, ballSpeedY, blockList, score, win, numberOfScoreList, totalScore, level, levelNo):
    ballCentre = ball.getCenter()
    ballCentreX = int(ballCentre.getX())
    ballCentreY = int(ballCentre.getY())
    for currentBlock in blockList:
        if currentBlock[2] <= ballCentreX + ballRadius and currentBlock[3] >= \
                ballCentreY - ballRadius and currentBlock[4] >= ballCentreX - \
                ballRadius and currentBlock[5] <= ballCentreY + ballRadius:
            # Deletes hit block from window
            currentBlock[0].undraw()
            # Deletes hit block from blockList
            blockList.remove(currentBlock)
            ballSpeedY = -ballSpeedY
            ballSpeedX = random.random() * directionSpeedChangeX - (directionSpeedChangeX / 2)
            # Change score
            score = scoreAmount(win, score, currentBlock[1], numberOfScoreList, totalScore)
            # Change level
            ballSpeedY, level, leveledUp = await setLevel(win, blockList, ballSpeedY, level, levelNo)
            # Recolour the remaining blocks only when the level actually changed
            # (not on every hit) — that "on every hit" version is what froze the
            # original game.
            if leveledUp:
                recolourBlocks(blockList, level)
            break
    return score, ballSpeedX, ballSpeedY, level


# Checks the bats location so python either hits the ball or ends the game
def checkBat(bat, ball, ballSpeedX, ballSpeedY):
    ballCentre = ball.getCenter()
    ballX = ballCentre.getX()
    ballY = ballCentre.getY() - ballRadius
    rightBat = bat.getP2().getX()
    leftBat = bat.getP1().getX()
    topBat = bat.getP1().getY()
    if ballY <= topBat and ballY >= topBat + ballSpeedY \
            and ballX <= rightBat + ballRadius and ballX >= leftBat - ballRadius:
        ballSpeedY = -ballSpeedY
        ballSpeedX = random.random() * directionSpeedChangeX - (directionSpeedChangeX / 2)
    return ballSpeedX, ballSpeedY


# Moves Bat
def moveBat(court, bat):
    click = court.checkMouse()
    dx = 0
    # Web/touch adaptation: when a finger (or held mouse) is pressed in the play
    # area, steer the bat continuously toward the pointer's x — up to the bat's
    # step speed per frame, easing as it nears the target so it settles smoothly.
    # On desktop a plain tap releases before the next frame, so it falls through
    # to the original click-to-nudge behaviour below.
    if court.pointerActive():
        batCentreX = (bat.getP1().getX() + bat.getP2().getX()) / 2
        diff = court.pointerX() - batCentreX
        if diff > 0 and bat.getP2().getX() < 99:
            dx = min(3, diff)
        elif diff < 0 and bat.getP1().getX() > 1:
            dx = max(-3, diff)
    elif click != None:
        clickX = click.getX()
        if clickX < 50 and bat.getP1().getX() > 1:
            dx = -3
        elif clickX > 50 and clickX <= 100 and bat.getP2().getX() < 99:
            dx = 3
    bat.move(dx, 0)
    # Return click as having two checkMouse() slowed the program down considerably (used for stop button)
    return click


# Keeps track of the score. scoreList[0] adds to the total score,
# Every other scoreList[] adds to the individual colour score
def scoreAmount(win, scoreList, colour, numberOfScoreList, totalScore):
    if colour == "Blue":
        scoreList[0] += 5
        scoreList[1] += 1
        numberOfScoreList[4].setText(scoreList[1])
    elif colour == "Green":
        scoreList[0] += 10
        scoreList[2] += 1
        numberOfScoreList[3].setText(scoreList[2])
    elif colour == "Yellow":
        scoreList[0] += 20
        scoreList[3] += 1
        numberOfScoreList[2].setText(scoreList[3])
    elif colour == "Orange":
        scoreList[0] += 40
        scoreList[4] += 1
        numberOfScoreList[1].setText(scoreList[4])
    elif colour == "Red":
        scoreList[0] += 80
        scoreList[5] += 1
        numberOfScoreList[0].setText(scoreList[5])
    totalScore.setText(scoreList[0])
    return scoreList


def setTimer(timer, start, newTime, oldTime):
    oldTime = newTime
    timer.setText(oldTime)
    return oldTime


# Changes the level, increasing the ball speed. Also reports whether the level
# actually changed this call, so the caller can recolour the blocks just once
# per level-up rather than on every block hit.
async def setLevel(win, blockList, ballSpeedY, level, levelNo):
    amountOfBlocks = 130
    blockToLevel = amountOfBlocks // 10 * level
    speedUpBall = ballSpeedY * 1.125
    leveledUp = False
    if len(blockList) == amountOfBlocks - blockToLevel:
        ballSpeedY = speedUpBall
        level += 1
        leveledUp = True
        levelNo.setText(level)
        levelUp = drawText(win, Point(50, 40), "Level Up!", 36)
        await asyncio.sleep(1)
        levelUp.undraw()
    return ballSpeedY, level, leveledUp


# Repaints the remaining blocks to reflect the current level. This is the
# feature the original game had to disable: under Zelle's tkinter graphics each
# setFill/setOutline forces a synchronous redraw, so doing it on every block hit
# froze the game. Here it runs ONCE per level-up (see checkBlocks), and the web
# graphics.py is retained-mode (one repaint per animation frame regardless), so
# it's cheap. Each block stores its own original colour in block[1].
def recolourBlocks(blockList, level):
    # Faithful to the original's (commented-out) intent:
    #   even levels      -> black fill, outline left as the block's own colour
    #                       (so on the dark theme they read as colour-outlined)
    #   level 5          -> black fill, white outline
    #   other odd levels -> restore the block's original colour (fill + outline)
    if level == 10:
        for block in blockList:
            block[0].setFill("gold")
            block[0].setOutline("gold")
    elif level % 2 == 0:
        for block in blockList:
            block[0].setFill("black")
            block[0].setOutline(block[1])
    elif level == 5:
        for block in blockList:
            block[0].setFill("black")
            block[0].setOutline("white")
    else:
        for block in blockList:
            block[0].setFill(block[1])
            block[0].setOutline(block[1])


# Checks whether the game should keep going
def checkGameOver(ball, blockList, win, click, stopButton):
    if len(blockList) == 0:
        gameOver = True
        return gameOver
    elif click != None:
        endGame = buttonPress(click, stopButton)
        if endGame == True:
            gameOver = True
            return gameOver
    else:
        centre = ball.getCenter()
        return centre.getY() < 0


# Section 3: After the game has finished
# Tells python what to do when the game ends
async def gameEnded(win, scoreList, dividerList, start, superList, blockList, duration):
    await asyncio.sleep(0.5)
    for i in range(3):
        dividerList[i].undraw()
    gameOverMessage = drawText(win, Point(50, 55), "Game Over!", 35)
    name = ""
    # Makes the user enter a name, numbers do not matter
    while len(name) < 3 or len(name) > 10:
        name = await addHighScore(win)
        if len(name) < 3 or len(name) > 10:
            # Displays an invalid entry textbox
            invalidEntry = drawRectangle(win, Point(10, 90), Point(130, 10), "red4")
            invalidEntryText = drawText(win, Point(70, 50), "Invalid Entry\n\nEntries \
must be:\n- a minimum of 3 characters\n- a maximum of 10          ", 30)
            invalidEntryText.setStyle("bold")
            await asyncio.sleep(3)
            invalidEntry.undraw(), invalidEntryText.undraw()
        else:
            await writeToFile(name, scoreList[0])
            break
    # Creates lists to find the highScores
    highScoresList, findHighScoreList = await highScoresLists()
    finalScore = scoreList[0]
    # Displays new high score if the final score is larger than the largest number in findHighScoreList
    if max(findHighScoreList) <= finalScore:
        gameOverMessage.setText("Congratulations {0}!\nNew High Score!".format(name))
        gameOverMessage.setSize(26)
    else:
        gameOverMessage.setText("Thanks for playing \n{0}".format(name))
        gameOverMessage.setSize(28)
    # Creates the final stats (scores, time)
    endScore = drawText(win, Point(50, 42), "Score: {0} ".format(finalScore), 25)
    totalMinutes = (duration) // 60
    totalSeconds = (duration) % 60
    endTime = drawText(win, Point(50, 32), "Total Time: \n{0} Minutes and {1} Seconds ".format(totalMinutes, totalSeconds), 25)
    exitButton, restartButton, viewHighScore, gameEndedList = gameEndedButtons(win)
    while True:
        click = await win.getMouse()
        if click != None:
            exit = buttonPress(click, exitButton)
            restart = buttonPress(click, restartButton)
            seeHighScores = buttonPress(click, viewHighScore)
            # Exit button
            if exit == True:
                await exitButtonPressed(win)
            # Restarts game
            elif restart == True:
                # To restart undraw everything
                for h in range(3):
                    for i in range(len(superList[h])):
                        superList[h][i].undraw()
                for j in range(2):
                    superList[j + 3].undraw()
                gameOverMessage.undraw(), endScore.undraw(), endTime.undraw()
                for k in range(len(gameEndedList)):
                    gameEndedList[k].undraw()
                for l in range(len(blockList)):
                    blockList[l][0].undraw()
                await subMain(win)
            # Shows the highscores
            elif seeHighScores == True:
                await showHighScore(win, highScoresList, findHighScoreList)


async def highScoresLists():
    # Pull the shared leaderboard; fall back to the local cache if offline.
    highScoresList = await _fetch_remote_scores()
    if highScoresList is None:
        highScoresList = _local_scores_lists()
    # Adds all the high scores to a list in integers to help find the scores easier
    findHighScoreList = []
    for i in range(len(highScoresList)):
        findHighScoreList.append(int(highScoresList[i][1]))
    # Guard max()/findHighScore against an empty leaderboard
    if not findHighScoreList:
        findHighScoreList.append(0)
    return highScoresList, findHighScoreList


# Draws the buttons and text after the game has ended
def gameEndedButtons(win):
    exitButton = drawRectangle(win, Point(25, 25), Point(45, 20), "orange4")
    exitButtonText = drawText(win, Point(35, 22.5), "Close Window", 12)
    restartButton = drawRectangle(win, Point(55, 25), Point(75, 20), "orange4")
    restartButtonText = drawText(win, Point(65, 22.5), "Restart Game", 12)
    viewHighScore = drawRectangle(win, Point(35, 17.5), Point(65, 7.5), "blue4")
    viewHighScoreText = drawText(win, Point(50, 12.5), "View High Scores", 14)
    gameEndedList = [exitButton, exitButtonText, restartButton,
                     restartButtonText, viewHighScore, viewHighScoreText]
    return exitButton, restartButton, viewHighScore, gameEndedList


# Enables three different buttons to be opened when the user chooses to close the window
async def exitButtonPressed(win):
    closePrompt = drawRectangle(win, Point(10, 80), Point(90, 20), "black")
    closePromptTitle = drawText(win, Point(50, 70), "Close Window", 30)
    closePrompt.setOutline("white")
    closeAndResetButton = drawRectangle(win, Point(37, 40), Point(63, 30), "red4")
    closeAndResetText = drawText(win, Point(50, 35), "Close and reset\nHigh Scores", 12)
    justCloseButton = drawRectangle(win, Point(12, 40), Point(34, 30), "red4")
    justCloseText = drawText(win, Point(23, 35), "Close", 12)
    cancelButton = drawRectangle(win, Point(66, 40), Point(88, 30), "red4")
    cancelText = drawText(win, Point(77, 35), "Cancel", 12)
    cancelCloseList = [closePrompt, closePromptTitle, closeAndResetButton,
                       closeAndResetText, justCloseButton, justCloseText, cancelButton, cancelText]
    while True:
        closeClick = await win.getMouse()
        if closeClick != None:
            closeAndReset = buttonPress(closeClick, closeAndResetButton)
            justClose = buttonPress(closeClick, justCloseButton)
            cancel = buttonPress(closeClick, cancelButton)
            # Closes the window and resets ONLY this device's local cache.
            # The shared online leaderboard is global and is deliberately not
            # wiped from the client (any visitor could otherwise reset everyone).
            if closeAndReset == True:
                localStorage.setItem(SCORE_KEY, DEFAULT_SCORES)
                win.close()
                raise SystemExit("Game Closed!")
            elif justClose == True:
                win.close()
                raise SystemExit("Game Closed!")
            # Cancel button to avoid misclicks
            elif cancel == True:
                for close in range(len(cancelCloseList)):
                    cancelCloseList[close].undraw()
                return


# Creates entry box for high score, and helps the button operate
async def addHighScore(win):
    user = Entry(Point(50, 40), 10)
    user.setFill("white"), user.setTextColor("black"), user.setFace("courier")
    user.draw(win)
    continueBox = drawRectangle(win, Point(35, 35), Point(65, 25), "yellow4")
    continueBoxText = drawText(win, Point(50, 30), "Continue", 20)
    while True:
        click = await win.getMouse()
        if click != None:
            continueB = buttonPress(click, continueBox)
            if continueB == True:
                break
    userString = user.getText()
    user.undraw(), continueBox.undraw(), continueBoxText.undraw()
    return userString


async def showHighScore(win, highScoresList, findHighScoreList):
    # Makes a high score list be shown, with N/A if there are not enough scores
    highScoresList, findHighScoreList = await highScoresLists()
    background = drawRectangle(win, Point(0, 0), Point(140, 100), "black")
    title = drawText(win, Point(70, 90), "High Scores", 36)
    returnButton = drawRectangle(win, Point(40, 20), Point(100, 10), "red4")
    returnButtonText = drawText(win, Point(70, 15), "Return to game", 25)
    listToUndraw = []
    # So N/A doesn't display at the start
    ensureTenScores = "II"
    timesPrinted = 0
    for scoreList in range(10):
        # Finds the highest score
        if scoreList == 0:
            highestNumber = max((findHighScoreList))
        # Finds the second highest score
        else:
            highestNumber, ensureTenScores = findHighScore(findHighScoreList)
        moveDown = scoreList * 5
        highScoreNumber = drawText(win, Point(45, 70 - moveDown), "{0}.".format(scoreList + 1), 20)
        listToUndraw.append(highScoreNumber)
        # Display the name and the score
        for highScore in highScoresList:
            if highScore[1] == str(highestNumber):
                score = drawText(win, Point(95, 70 - moveDown), highScore[1], 20)
                name = drawText(win, Point(70, 70 - moveDown), highScore[0], 20)
                listToUndraw.append(score)
                listToUndraw.append(name)
                highScoresList.remove(highScore)
                timesPrinted += 1
                break
    # Fill rest with N/A
    moveDownFurther = 0
    while timesPrinted != 10:
        moveDownFurther = timesPrinted * 5
        notApp = drawText(win, Point(70, 70 - moveDownFurther), "N/A", 20)
        listToUndraw.append(notApp)
        timesPrinted += 1
    # For buttons
    while True:
        click = await win.getMouse()
        returnScreen = buttonPress(click, returnButton)
        if returnScreen == True:
            background.undraw(), title.undraw(), returnButton.undraw()
            returnButtonText.undraw()
            for unDraw in range(len(listToUndraw)):
                listToUndraw[unDraw].undraw()
            break


# Attempts to find the second Highest score
def findHighScore(findHighScoreList):
    entriesInList = 0
    # ('-inf') is infinity
    numberOne = numberTwo = float('-inf')
    for highestNumber in findHighScoreList:
        entriesInList += 1
        if highestNumber > numberTwo:
            if highestNumber >= numberOne:
                numberOne, numberTwo = highestNumber, numberOne
            else:
                numberTwo = highestNumber
    if entriesInList >= 2:
        findHighScoreList.remove(numberTwo)
        return numberTwo, findHighScoreList
    else:
        return False, findHighScoreList


# Adds name and score to the shared leaderboard (and the local fallback cache)
async def writeToFile(name, score):
    _local_write(name, score)
    await _post_remote_score(name, score)


# Enables buttons to be clicked on
def buttonPress(click, button):
    if button.getP1().getX() <= click.getX() and \
            button.getP1().getY() >= click.getY() \
            and button.getP2().getX() >= click.getX() and \
            button.getP2().getY() <= click.getY():
        return True
    else:
        return False
