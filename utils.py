import os
import subprocess
import xml.etree.ElementTree as ET
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# !!! WARNING: Hardcoding tokens is INSECURE. Use environment variables in production. !!!
# Replace <YOUR_GITLAB_PERSONAL_ACCESS_TOKEN> with the token you generated in GitLab.
GITLAB_PERSONAL_ACCESS_TOKEN = ""


def clone_repo(git_url, clone_dir):
    logging.info(f"Attempting to clone/update {git_url} into {clone_dir}")

    # Construct the authenticated URL using the Personal Access Token
    if git_url.startswith("https://gitlab.com/"):
        authenticated_git_url = git_url.replace(
            "https://gitlab.com/",
            f"https://oauth2:{GITLAB_PERSONAL_ACCESS_TOKEN}@gitlab.com/"
        )
    else:
        logging.error(f"Unsupported Git URL format: {git_url}")
        return False, f"Unsupported Git URL format: {git_url}"

    if os.path.exists(clone_dir):
        logging.info(f"Directory {clone_dir} already exists. Attempting to pull latest changes.")
        pull_command = ["git", "-C", clone_dir, "pull", authenticated_git_url]
        logging.info(f"Running pull command: git -C {clone_dir} pull https://oauth2:*****@gitlab.com/...")

        try:
            result = subprocess.run(
                pull_command,
                capture_output=True,
                text=True,
                check=False
            )
            logging.info(f"Pull subprocess finished. Return code: {result.returncode}")
            if result.stdout: logging.info(f"Pull subprocess STDOUT:\n{result.stdout}")
            if result.stderr: logging.info(f"Pull subprocess STDERR:\n{result.stderr}")

            if result.returncode != 0:
                logging.error(f"Git pull command failed with return code {result.returncode}")
                return False, result.stderr.strip() if result.stderr else f"Git pull failed with code {result.returncode}"

            logging.info("Pull successful via subprocess.")
            return True, "Directory already exists, updated successfully."

        except FileNotFoundError:
            logging.error("Git command not found for pull. Is Git installed and in your PATH?")
            return False, "Git command not found for pull."
        except Exception as e:
            logging.error(f"An unexpected error occurred during subprocess pull: {e}")
            return False, f"Directory exists but an unexpected error occurred during update: {e}"

    logging.info(f"Directory {clone_dir} does not exist. Attempting to clone using subprocess with token.")
    clone_command = ["git", "clone", authenticated_git_url, clone_dir]
    logging.info(f"Running clone command: git clone https://oauth2:*****@gitlab.com/... {clone_dir}")

    try:
        result = subprocess.run(
            clone_command,
            capture_output=True,
            text=True,
            check=False
        )
        logging.info(f"Clone subprocess finished. Return code: {result.returncode}")
        if result.stdout: logging.info(f"Clone subprocess STDOUT:\n{result.stdout}")
        if result.stderr: logging.info(f"Clone subprocess STDERR:\n{result.stderr}")

        if result.returncode != 0:
            logging.error(f"Git clone command failed with return code {result.returncode}")
            return False, result.stderr.strip() if result.stderr else f"Git clone failed with code {result.returncode}"

        logging.info("Cloning successful via subprocess.")
        return True, "Cloned successfully"

    except FileNotFoundError:
        logging.error("Git command not found. Is Git installed and in your PATH?")
        return False, "Git command not found."
    except Exception as e:
        logging.error(f"An unexpected error occurred during subprocess cloning: {e}")
        return False, str(e)


# --- UPDATED detect_java_version ---
def detect_java_version(project_dir):
    logging.info(f"Detecting Java version in {project_dir}")
    current_version = "Unknown"
    suggested_versions = ["11", "17", "21"] # Common upgrade targets

    # Check for pom.xml
    pom_path = os.path.join(project_dir, "pom.xml")
    if os.path.exists(pom_path):
        logging.info(f"Found pom.xml at {pom_path}. Parsing...")
        try:
            tree = ET.parse(pom_path)
            root = tree.getroot()
            ns = {'mvn': 'http://maven.apache.org/POM/4.0.0'}
            # Look for maven.compiler.source
            for prop in root.findall(".//mvn:properties", ns):
                java_version_element = prop.find("mvn:maven.compiler.source", ns)
                if java_version_element is not None and java_version_element.text:
                    current_version = java_version_element.text.strip()
                    logging.info(f"Detected Java version from maven.compiler.source: {current_version}")
                    break # Found it, no need to search further in properties
            # If not found in maven.compiler.source, look for java.version
            if current_version == "Unknown":
                for prop in root.findall(".//mvn:properties", ns):
                    java_version_element = prop.find("mvn:java.version", ns)
                    if java_version_element is not None and java_version_element.text:
                        current_version = java_version_element.text.strip()
                        logging.info(f"Detected Java version from java.version: {current_version}")
                        break # Found it

        except Exception as e:
            logging.error(f"Error parsing pom.xml: {e}")
            # Continue to check other files if parsing fails
            pass

    # Check for build.gradle (simplified to find first relevant line)
    if current_version == "Unknown":
        gradle_path = os.path.join(project_dir, "build.gradle")
        if os.path.exists(gradle_path):
            logging.info(f"Found build.gradle at {gradle_path}. Parsing...")
            try:
                with open(gradle_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("sourceCompatibility") or line.startswith("targetCompatibility"):
                            parts = line.split()
                            if len(parts) > 1:
                                # Get the version part, handle quotes and potential semicolons
                                version_part = parts[-1].strip("'").strip('"').strip(';')
                                if version_part:
                                     current_version = version_part
                                     logging.info(f"Detected Java version from build.gradle: {current_version}")
                                     break # Found it

            except Exception as e:
                logging.error(f"Error parsing build.gradle: {e}")
                pass # Continue if parsing fails

    # Filter suggested versions to be higher than the current detected version (if possible)
    try:
        current_major_version = int(float(current_version)) # Handle versions like "1.8"
        filtered_suggestions = [v for v in suggested_versions if int(v) > current_major_version]
        suggested_versions = filtered_suggestions
        logging.info(f"Filtered suggested versions: {suggested_versions}")
    except ValueError:
        logging.warning(f"Could not parse current version '{current_version}' to filter suggestions.")
        # If current version is unknown or unparseable, keep all suggestions
        pass


    logging.info(f"Final detected Java version: {current_version}, Suggested: {suggested_versions}")
    return {"current_version": current_version, "suggested_versions": suggested_versions}

# --- NEW Function to find Java files ---
def find_java_files(project_dir):
    java_files = []
    for root, _, files in os.walk(project_dir):
        for file in files:
            if file.endswith(".java"):
                 # Exclude files in build or target directories if they exist
                 if "build" not in root and "target" not in root:
                    java_files.append(os.path.join(root, file))
    logging.info(f"Found {len(java_files)} Java files.")
    return java_files