import streamlit as st
import requests
import json # Import json

# --- Configuration ---
BACKEND_URL = "http://localhost:8000"

st.title("Java Upgrade Assistant")

git_url = st.text_input("Enter GitLab Project URL:")

# Use session state to store repo_path, current_version, suggested_versions
if 'repo_path' not in st.session_state:
    st.session_state['repo_path'] = None
if 'current_java_version' not in st.session_state:
    st.session_state['current_java_version'] = None
if 'suggested_java_versions' not in st.session_state:
    st.session_state['suggested_java_versions'] = []


if st.button("Clone and Analyze"):
    if not git_url:
        st.warning("Please enter a GitLab URL.")
    else:
        with st.spinner("Cloning and analyzing..."):
            try:
                resp = requests.post(f"{BACKEND_URL}/clone_and_detect", json={"git_url": git_url})
                resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                data = resp.json()

                st.session_state['repo_path'] = data.get('repo_path')
                st.session_state['current_java_version'] = data.get('current_java_version')
                st.session_state['suggested_java_versions'] = data.get('suggested_java_versions', [])

                if st.session_state['current_java_version'] and st.session_state['current_java_version'] != "Unknown":
                    st.success(f"Analysis complete. Detected Java version: **{st.session_state['current_java_version']}**")
                    if st.session_state['suggested_java_versions']:
                        st.info(f"Suggested upgrade targets: {', '.join(st.session_state['suggested_java_versions'])}")
                    else:
                        st.info("No higher Java versions suggested (perhaps already at the latest supported).")
                elif st.session_state['repo_path']:
                     st.warning("Could not detect current Java version from project configuration.")
                else:
                     st.error("Cloning and analysis failed. Check logs for details.")


            except requests.exceptions.RequestException as e:
                st.error(f"Error connecting to backend or during analysis: {e}")
            except Exception as e:
                 st.error(f"An unexpected error occurred during analysis: {e}")


# --- Display upgrade options if analysis was successful ---
if st.session_state['repo_path'] and st.session_state['current_java_version'] != "Unknown":
    st.subheader("Java Upgrade")

    # Add a dropdown for target version
    if st.session_state['suggested_java_versions']:
        target_version = st.selectbox(
            "Select Target Java Version:",
            st.session_state['suggested_java_versions']
        )

        # Add a dropdown/input for Ollama model (optional, defaults to llama3 in backend)
        ollama_model = st.text_input("Ollama Model (e.g., llama3, codellama):", value="llama3")


        if st.button("Upgrade Code"):
            if not target_version:
                st.warning("Please select a target Java version.")
            else:
                with st.spinner(f"Upgrading code to Java {target_version} using Ollama model '{ollama_model}'..."):
                    try:
                        upgrade_data = {
                            "repo_path": st.session_state['repo_path'],
                            "target_version": target_version,
                            "ollama_model": ollama_model # Pass the selected model
                        }
                        resp = requests.post(f"{BACKEND_URL}/upgrade_java", json=upgrade_data)
                        resp.raise_for_status() # Raise HTTPError for bad responses

                        upgrade_result = resp.json()

                        if "status" in upgrade_result:
                            if "errors" in upgrade_result.get("details", ""): # Check for errors in details string
                                st.warning(f"Upgrade Status: {upgrade_result['status']}")
                                for detail in upgrade_result.get("details", "").splitlines():
                                     st.write(detail) # Display error details
                            elif "errors" in upgrade_result: # Check for errors list directly
                                st.warning(f"Upgrade Status: {upgrade_result['status']}")
                                for err in upgrade_result['details']:
                                    st.error(err)
                            else:
                                st.success(f"Upgrade Status: {upgrade_result['status']}")
                        else:
                            st.json(upgrade_result) # Display raw result if format unexpected

                    except requests.exceptions.RequestException as e:
                        st.error(f"Error calling upgrade endpoint: {e}")
                    except Exception as e:
                        st.error(f"An unexpected error occurred during upgrade: {e}")
    else:
        st.info("No upgrade options available for the detected Java version.")


    # Add button to open in VS Code again after upgrade attempt
    if st.session_state['repo_path']:
        if st.button("Open Project in VS Code"):
            with st.spinner("Opening VS Code..."):
                try:
                    resp = requests.post(f"{BACKEND_URL}/open_vscode", data={"repo_path": st.session_state['repo_path']})
                    resp.raise_for_status() # Raise HTTPError for bad responses
                    data = resp.json()
                    if "error" in data:
                        st.error(data["error"])
                    else:
                        st.success(data["status"])
                except requests.exceptions.RequestException as e:
                    st.error(f"Error opening VS Code: {e}")
                except Exception as e:
                     st.error(f"An unexpected error occurred: {e}")
