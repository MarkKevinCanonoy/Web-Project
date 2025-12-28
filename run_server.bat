@echo off
:: turns off the messy command display

:: check if the 'venv' folder already exists
:: if it does not exist, we create it using python 3.12
if not exist venv (
    echo [system] virtual environment not found. creating one now...
    py -3.12 -m venv venv
)

:: activate the virtual environment
:: we use 'call' to make sure the script continues after activation
call venv\Scripts\activate

call pip install -r requirements.txt

:: tell the user what is happening
echo [system] starting the school clinic server...

:: run the server with auto-reload
python -m uvicorn main:app --reload

:: keep the window open if the server crashes so you can see the error
pause