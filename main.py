from fastapi import FastAPI, Form, HTTPException
from pydantic import BaseModel
import os
import subprocess
import requests # Import requests for Ollama API call
from .utils import clone_repo, detect_java_version, find_java_files # Import find_java_files
import logging

# Configure basic logging (if not already done in utils, good to have here too)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# --- NEW BaseModel for Upgrade Request ---
class UpgradeRequest(BaseModel):
    repo_path: str
    target_version: str
    ollama_model: str = "codeup:latest" # Default Ollama model

# --- Updated Clone Request (if needed, but BaseModel is fine) ---
class CloneRequest(BaseModel):
    git_url: str

@app.post("/clone_and_detect")
def clone_and_detect(req: CloneRequest):
    logging.info(f"Received request to clone and detect: {req.git_url}")
    # Derive a safe directory name from the URL
    # Replace characters that might be invalid in filenames
    repo_name_safe = req.git_url.rstrip('/').split('/')[-1].replace('.git', '').replace('.', '_').replace('-', '_')
    clone_dir = os.path.join("/tmp", repo_name_safe) # Use safe name for directory

    success, msg = clone_repo(req.git_url, clone_dir)
    if not success:
        logging.error(f"Clone/update failed: {msg}")
        raise HTTPException(status_code=500, detail=f"Cloning failed: {msg}") # Use HTTPException for FastAPI errors

    version_info = detect_java_version(clone_dir)
    current_version = version_info["current_version"]
    suggested_versions = version_info["suggested_versions"]

    logging.info(f"Successfully cloned/updated {clone_dir}, detected Java version: {current_version}")
    # Return current and suggested versions
    return {"repo_path": clone_dir, "current_java_version": current_version, "suggested_java_versions": suggested_versions}

@app.post("/open_vscode")
def open_vscode(repo_path: str = Form(...)):
    logging.info(f"Received request to open VS Code for: {repo_path}")
    try:
        # Ensure the path is valid before attempting to open
        if not os.path.isdir(repo_path):
             logging.error(f"Provided path is not a directory: {repo_path}")
             raise HTTPException(status_code=400, detail=f"Invalid repository path: {repo_path}")

        # Check if 'code' command is available in PATH
        try:
            subprocess.run(["which", "code"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
             logging.error("'code' command not found in PATH.")
             raise HTTPException(status_code=500, detail="'code' command not found. Please install VS Code shell command.")

        subprocess.Popen(["code", repo_path])
        logging.info("Attempted to open VS Code.")
        return {"status": "VS Code opened"}
    except HTTPException as e:
        raise e # Re-raise FastAPI HTTPExceptions
    except Exception as e:
        logging.error(f"Failed to open VS Code: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open VS Code: {e}") # Catch other exceptions and return 500

# --- NEW Endpoint for Java Upgrade ---
@app.post("/upgrade_java")
def upgrade_java(req: UpgradeRequest):
    repo_path = req.repo_path
    target_version = req.target_version
    ollama_model = req.ollama_model
    ollama_api_url = "http://localhost:11434/api/generate" # Default Ollama API endpoint

    logging.info(f"Received request to upgrade Java in {repo_path} to version {target_version} using model {ollama_model}")

    if not os.path.isdir(repo_path):
        logging.error(f"Invalid repository path for upgrade: {repo_path}")
        raise HTTPException(status_code=400, detail=f"Invalid repository path: {repo_path}")

    # 1. Detect current Java version (again, or assume it's passed/stored)
    # For simplicity now, we'll re-detect. In a real app, pass it or store in session.
    version_info = detect_java_version(repo_path)
    current_version = version_info["current_version"]

    if current_version == "Unknown":
        logging.warning(f"Could not detect current Java version in {repo_path}. Cannot proceed with upgrade.")
        raise HTTPException(status_code=400, detail="Could not detect current Java version. Cannot proceed with upgrade.")

    if current_version == target_version:
         return {"status": f"Project is already at target Java version {target_version}"}

    logging.info(f"Upgrading from Java {current_version} to {target_version}")

    # 2. Find relevant files
    java_files = find_java_files(repo_path)
    pom_path = os.path.join(repo_path, "pom.xml")
    gradle_path = os.path.join(repo_path, "build.gradle")

    relevant_files = java_files
    if os.path.exists(pom_path):
        relevant_files.append(pom_path)
    if os.path.exists(gradle_path):
        relevant_files.append(gradle_path)

    if not relevant_files:
        logging.warning(f"No Java files, pom.xml, or build.gradle found in {repo_path}")
        return {"status": "No relevant files found for upgrade."}

    logging.info(f"Found {len(relevant_files)} relevant files for upgrade.")

    # 3. Read file contents and prepare prompt for Ollama
    file_contents = {}
    for file_path in relevant_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                file_contents[file_path] = f.read()
        except Exception as e:
            logging.error(f"Could not read file {file_path}: {e}")
            # Decide if you want to skip this file or fail the upgrade
            # For now, we'll log and continue with other files
            continue

    # Prepare the prompt for the LLM
    prompt = f"You are a senior Java developer assistant tasked with upgrading a Java project.\n"
    prompt += f"The project is currently using Java version {current_version} and needs to be upgraded to Java version {target_version}.\n"
    prompt += f"Carefully review the provided code and configuration files. Make the necessary changes to:\n"
    prompt += f"- Update dependencies and compiler/runtime versions in pom.xml or build.gradle.\n"
    prompt += f"- Update Java source code to use features available in Java {target_version} and fix any compatibility issues or deprecations from Java {current_version}.\n"
    prompt += f"- Modernize usage of legacy Java APIs (e.g., replace Vector/Enumeration with ArrayList/Iterator, update file I/O, networking, etc.) where appropriate.**\n"
    prompt += f"- Ensure the code follows best practices for Java {target_version}.\n\n"
    # Clarify the required output format for the LLM, emphasizing the file path after the backticks.
    # Correcting the f-string syntax.
    prompt += f'Respond ONLY with the FULL content of the modified files. For each file that requires changes, provide the full content within a markdown code block. It is crucial that you include the file path relative to the repository root immediately after the opening triple backticks, like this:\n\n```path/to/modified/file.java\n// Full upgraded code for this file\n```\n\nIf a file does not need changes, do NOT include it in your response.\n\n'

    prompt += f"Here are the relevant files from the project:\n\n"

    for file_path, content in file_contents.items():
        prompt += f"--- File: {file_path} ---\n"
        prompt += f"```\n{content}\n```\n\n"

    logging.info(f"Prepared prompt for Ollama (partial display):\n{prompt[:500]}...") # Log partial prompt


    # 4. Call Ollama API
    try:
        logging.info(f"Calling Ollama API at {ollama_api_url} with model {ollama_model}")
        response = requests.post(
            ollama_api_url,
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False # Set stream to False to get the full response at once
            },
            timeout=600 # Set a generous timeout (10 minutes) for the LLM response
        )
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        ollama_response_data = response.json()
        llm_output = ollama_response_data.get("response", "").strip()
        logging.info(f"Received FULL raw response from Ollama:\n{llm_output}") # Log the full raw response

    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling Ollama API: {e}")
        raise HTTPException(status_code=500, detail=f"Error calling Ollama API: {e}. Ensure Ollama is running and accessible at {ollama_api_url} and the model '{ollama_model}' is downloaded.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing Ollama response: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred with Ollama response: {e}")


    # 5. Parse LLM response and apply changes
    # The LLM is instructed to return markdown code blocks with file paths.
    # We need to parse this format.
    updated_files_count = 0
    errors_applying_changes = []

    # New parsing logic for the LLM's output format
    lines = llm_output.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- File: ") and line.endswith(" ---"):
            # Found a file path line, extract the path
            file_path_relative = line[len("--- File: "): -len(" ---")].strip()
            # Construct the absolute path
            abs_file_path = os.path.join(repo_path, file_path_relative)

            # Basic path traversal check
            if os.path.commonpath([os.path.realpath(repo_path), os.path.realpath(abs_file_path)]) != os.path.realpath(repo_path):
                logging.warning(f"Skipping potentially unsafe path from LLM: {file_path_relative}")
                i += 1
                continue # Skip this file

            i += 1 # Move to the next line
            if i < len(lines) and lines[i].strip() == "```":
                # Found the start of the code block, collect content until the next ```
                i += 1 # Move past the opening ```
                file_content_lines = []
                while i < len(lines) and lines[i].strip() != "```":
                    file_content_lines.append(lines[i])
                    i += 1

                # If we are at the end of lines or found the closing ```
                if i < len(lines) and lines[i].strip() == "```":
                    # Found closing ```, save the file
                    try:
                        full_content = "\n".join(file_content_lines)
                        # Ensure parent directory exists
                        os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
                        with open(abs_file_path, 'w', encoding='utf-8') as f:
                            f.write(full_content)
                        updated_files_count += 1
                        logging.info(f"Successfully wrote changes to {abs_file_path}")
                    except Exception as e:
                        logging.error(f"Could not write changes to file {abs_file_path}: {e}")
                        errors_applying_changes.append(f"Could not write changes to {os.path.basename(abs_file_path)}: {e}")
                    # Move past the closing ```
                    i += 1
                else:
                    # Code block was not properly closed
                    logging.warning(f"LLM response for file {file_path_relative} ended without a closing ```.")
                    errors_applying_changes.append(f"LLM response for {os.path.basename(file_path_relative)} was incomplete.")
                    # Continue parsing from the current line, hoping to find another file block
            else:
                # Expected a ``` after file path line but didn't find one
                logging.warning(f"Expected code block after file path {file_path_relative} but didn't find ```.")
                # Continue parsing from the current line
        else:
            # Not a file path line or start of a known block, skip
            i += 1

    logging.info(f"Upgrade process finished. Updated {updated_files_count} files.")

    if errors_applying_changes:
         error_message = "Upgrade completed with errors:\n" + "\n".join(errors_applying_changes)
         logging.error(error_message)
         # You might want to return a 500 status code or a detailed error message
         # depending on how critical these errors are.
         return {"status": "Upgrade finished with errors", "details": errors_applying_changes}

    return {"status": f"Successfully upgraded {updated_files_count} files to Java {target_version}"}
