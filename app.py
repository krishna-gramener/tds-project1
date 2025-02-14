from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import os
import openai
import subprocess
import json
import tempfile

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Load OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set. Please check your .env file.")

openai.api_key = OPENAI_API_KEY
openai.api_base = OPENAI_BASE_URL

def convert_path_to_windows(path):
    if path.startswith('/'):
        path = path.replace('/', '\\')
    return path

def execute_task(command: str, execution_type: str):
    """Executes a command based on its type (shell or Python)."""
    try:
        if execution_type == "shell":
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
        elif execution_type == "python":
            if not command.strip():
                return {"status": "error", "error": "Empty command received"}

            # Create a temporary file for script execution
            with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(command)
                print("Command",command)
                temp_script_path = temp_file.name  # Store temp file path

            # Ensure script dependencies are installed
            install_missing_dependencies(command)

            # Execute the Python script
            result = subprocess.run(["python", temp_script_path], capture_output=True, text=True)

            # Cleanup: Remove temp script after execution
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
    prompt = (
        f'You are a DataWorks automation agent that generates **fully executable** Python or Windows shell scripts. Your response must always be valid JSON and contain syntactically correct, runnable code.'
        'Given the task,generate a structured JSON response with a SINGLE step '
        'that contains a **fully executable** solution.\n\n'
        '### **Rules**\n'
        '- The output must be valid, **fully executable** Python code or shell commands.\n'
        '- Make sure the code is syntactically correct'
        '- Ensure Python scripts are properly formatted with actual newlines (avoid `\n` in strings).'
        '- [IMP]**Ensure Python scripts use **actual newlines** (avoid `\\n` escape sequences). Write full multi-line scripts.**'
        '- **Do not include syntax errors** (e.g., unterminated strings, missing brackets).\n'
        '- Always use **double quotes (")** for file paths and strings in Python.\n'
        '- If a string spans multiple lines, use triple quotes.\n'
        '- Test the script before returning to ensure it runs without errors.\n'
        '- Return only JSON. Do **not** include markdown (```json).\n\n'
        '- Use appropriate libraries (pillow for images, sqlite3 for databases)'
        '- Unless mentioned , Ensure that any files created or modified are only within the C:\\data\\ directory.'
        '- Use only **raw string** for paths'
        '- Format output exactly as specified,Ensure that the code can handle various data formats and includes error handling for invalid formats, including date formats. Handle and standardize dates from any format (e.g., YYYY-MM-DD, DD-MMM-YYYY, MMM DD, YYYY, YYYY/MM/DD HH:MM:SS, etc.) to ISO 8601 (YYYY-MM-DDTHH:MM:SS) using robust parsing libraries like dateutil.parser with error handling for invalid formats. If question is about counting / anything related to the dates' 

        '### **Expected JSON Format**\n'
        '{\n'
        '    "step": "<Step description>",\n'
        '    "command": "<Fully executable Python script or Shell command>",\n'
        '    "type": "<python or shell>"\n'
        '}'
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": task}
            ]
        )

        response_text = response["choices"][0]["message"]["content"].strip()
        print("Response Text:",response_text)
        if response_text.startswith("```json"):
            response_text = response_text[7:].strip()
        if response_text.endswith("```"):
            response_text = response_text[:-3].strip()

        step = json.loads(response_text)
        if not isinstance(step, dict) or "command" not in step or "type" not in step:
            raise HTTPException(status_code=400, detail="Invalid task format received from LLM")

        step["command"] = convert_path_to_windows(step["command"]).replace("\\n", "\n")


        result = execute_task(step["command"], step["type"])
        return {"status": "completed", "results": [result]}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned an invalid JSON response")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/read")
async def read_file(path: str = Query(..., description="File path to read")):
    """Returns the content of the specified file."""
    try:
        if not path.startswith("C:\\data"):
            raise HTTPException(status_code=403, detail="Access to external files is not allowed.")

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