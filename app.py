from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import os
import openai
import subprocess
import json
import tempfile
import re
import requests

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Load OpenAI API key
AIPROXY_TOKEN = os.getenv("AIPROXY_TOKEN")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

if not AIPROXY_TOKEN:
    raise ValueError("AIPROXY_TOKEN is not set. Please check your .env file.")

openai.api_key = AIPROXY_TOKEN
openai.api_base = OPENAI_BASE_URL

def convert_path_to_windows(path):
    if path.startswith('/'):
        path = path.replace('/', '\\')
    return path

def execute_task(command: str, execution_type: str):

    try:
        if execution_type == "shell":
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
        elif execution_type == "python":
            if not command.strip():
                return {"status": "error", "error": "Empty command received"}

            # Create a temporary file for script execution
            with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(command)
                temp_script_path = temp_file.name  

            # Ensure script dependencies are installed
            install_missing_dependencies(command)

            # Execute the Python script
            result = subprocess.run(["python", temp_script_path], capture_output=True, text=True)

            # Cleanup: Remove temp script after execution (this is allowed as it is a temporary file)
            os.remove(temp_script_path)
        else:
            return {"status": "error", "error": "Invalid execution type"}

        if result.returncode == 0:
            return {"status": "success", "output": result.stdout.strip()}
        else:
            return {"status": "error", "error": result.stderr.strip()}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def install_missing_dependencies(python_code: str):
    """Checks for missing Python modules and installs them."""
    import re
    import subprocess

    matches = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', python_code, re.MULTILINE)
    if not matches:
        return

    missing_modules = []
    for module in matches:
        try:
            print("Importing :",module)
            __import__(module)
        except ImportError:
            missing_modules.append(module)

    if missing_modules:
        subprocess.run(["pip", "install"] + missing_modules, capture_output=True, text=True)

@app.post("/run")
async def run_task(task: str):
    prompt = r'''
    
You are a DataWorks automation agent that generates fully executable Python or Windows shell scripts. 
Your response must always be valid JSON and contain syntactically correct, runnable code.

**TASKS**
    - Data processing, API fetching (save under C:\data), Git (clone/commit under C:\data), web scraping, image/audio processing, format conversions, CSV/JSON filtering, external script execution.

**Rules**
- Executable Code Only: The output must be fully executable Python code or shell commands.
- Valid Syntax: Ensure scripts are syntactically correct with no syntax errors (e.g., unterminated strings, missing brackets).
- Newline Handling:
    - Python scripts must use actual newlines instead of '\n'
    - DO NOT USE '\n' inside strings.
    - For multi-line strings, use triple quotes (""").
- String Formatting:
    Always use double quotes (") for file paths and strings in Python.
    Use raw strings (r"") for file paths.
- File Operations: Unless specified otherwise, restrict file creation/modification to C:\data\.
- Libraries & Dependencies
    Use appropriate libraries:
        - pillow for image processing
        - sqlite3 for database operations
        - Dates: ISO 8601, dateutil.parser, handle invalid formats.Handle and standardize dates from any format (e.g., YYYY-MM-DD, DD-MMM-YYYY, MMM DD, YYYY, YYYY/MM/DD HH:MM:SS, etc.) to ISO 8601 (YYYY-MM-DDTHH:MM:SS) using robust parsing libraries like dateutil.parser with error handling for invalid formats. If question is about counting / anything related to the dates'
    Ensure error handling for invalid data formats, especially for dates.
    
**Handling Images**
    - Convert images to Base64 encoding.    
    - Do not overwrite existing images.
    - Include "type": "image_url" and the encoded image in the JSON response.
    - If image processing or text extraction via LLM is required,use:
        API: https://llmfoundry.straive.com/gemini/v1beta/openai/chat/completions  
        Auth: Bearer {os.environ['AIPROXY_TOKEN']}:tds-project  
        Model: gemini-1.5-pro-latest  
        Handle API errors with appropriate error messages.
        
**Output Format**
    Return only valid JSON in the following format (no markdown or code blocks):
    json
    {
        "step": "<Step description>",
        "command": "<Fully executable Python script or Shell command>",
        "type": "<python or shell>"
    }
'''
    try:
        
        response = requests.post("https://llmfoundry.straive.com/openai/v1/chat/completions",headers={"Authorization": f"Bearer {os.environ['AIPROXY_TOKEN']}:tds-project"},json={"model": "gpt-4o-mini", "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": task}
            ]})
        rjson = response.json()  # Convert response to dictionary
        response_text = rjson["choices"][0]["message"]["content"].strip()

        print("Response Text:",response_text)
        if response_text.startswith("```json"):
            response_text = response_text[7:].strip()
        if response_text.endswith("```"):
            response_text = response_text[:-3].strip()

        step = json.loads(response_text)
        if not isinstance(step, dict) or "command" not in step or "type" not in step:
            raise HTTPException(status_code=400, detail="Invalid task format received from LLM")

        step["command"] = convert_path_to_windows(step["command"])
        print('Generated Command:',step["command"])

        result = execute_task(step["command"], step["type"])
        return {"status": "completed", "results": [result]}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned an invalid JSON response")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/read")
async def read_file(path: str = Query(..., description="File path to read")):
    """Returns the content of the specified file, only if it's inside C:\\data."""
    try:
        if not path.startswith("C:\\data"):
            raise HTTPException(status_code=403, detail="Access to external files is not allowed (B1).")

        path = convert_path_to_windows(path)

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="File not found.")

        with open(path, "r", encoding="utf-8") as file:
            content = file.read()

        return JSONResponse(content={"content": content})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=PlainTextResponse)
def display_homepage():
    return "Welcome to Localhost"