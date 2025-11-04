# GEMINI.md

## Project Overview

This project is a web application for managing sales, events, customers, and collaborators, likely for a bingo-related business. It is built with Python and the Flask web framework, using MongoDB as the database. The application provides a web interface for all CRUD (Create, Read, Update, Delete) operations.

The main technologies used are:
*   **Backend:** Python, Flask
*   **Database:** MongoDB (connected via `pymongo`)
*   **Frontend:** HTML, CSS, JavaScript (using templates)

The application connects to a MongoDB Atlas cluster. The connection URI is hardcoded in `app.py` but can be overridden by the `MONGODB_URI` environment variable.

## Building and Running

To run this project, you will need Python and `pip` installed.

1.  **Install Dependencies:**
    Install the required Python packages using the `requirements.txt` file:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the Application:**
    You can run the Flask application with the following command:
    ```bash
    flask run
    ```
    By default, the application will be available at `http://127.0.0.1:5000`.

    The application uses a MongoDB database. Ensure that the MongoDB server is running and accessible from the application. The connection string in `app.py` points to a cloud-based MongoDB Atlas cluster.

## Development Conventions

*   **Authentication:** The application uses a session-based authentication system. The `login_required` decorator is used to protect routes that require a logged-in user. Passwords are hashed using `bcrypt`.
*   **Database:** The application uses `pymongo` to interact with a MongoDB database. The database connection is managed using Flask's `g` object.
*   **Sequential IDs:** The application uses custom functions (`get_next_global_sequence`, `get_next_cliente_sequence`, etc.) to generate atomic, sequential integer IDs for new documents in the database. This is a common pattern when you need human-readable, sequential IDs instead of MongoDB's default `ObjectId`.
*   **Project Structure:** The main application logic is contained in `app.py`. HTML templates are located in the `templates/` directory, and static assets like CSS and JavaScript are in the `static/` directory.
*   **Error Handling:** The application has basic error handling, redirecting users with error messages for common issues like invalid login or database connection problems.
