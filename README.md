# PulsePet

PulsePet is a memory-driven AI companion web application I built as my final-year individual software engineering project.

The application explores how conversational AI can become more useful and consistent when it can remember selected user preferences across conversations. It is designed to support daily reflection, personalisation and more natural long-term interaction.

## Why I built it

Many basic chat applications treat every conversation as isolated, meaning users have to repeat information about themselves. PulsePet explores a more continuous approach by combining AI-generated responses with lightweight, user-controlled memory.

The project also allowed me to investigate how AI software could later connect to voice interaction, visual avatars and physical devices.

## Features

* User registration and login
* Authenticated chat sessions
* AI-generated conversational responses using the OpenAI API
* Persistent storage of selected user preferences
* Chat-history storage for each user
* Hybrid response routing for memory-related and general messages
* Clear Chat and Clear Memory controls
* Experimental voice and avatar extensions developed alongside the web MVP

## How it works

1. A user creates an account and logs into the application.
2. Messages are submitted through the Flask chat interface.
3. The application checks whether the message relates to stored preferences or requires a general conversational response.
4. Memory-related interactions are handled using local SQLite data.
5. General conversation is sent to the OpenAI API.
6. The response and conversation history are stored for the authenticated user.

For example, a user can state that they like a particular colour and ask about it again later. PulsePet can use the stored preference to provide a more personalised response.

## Evaluation

I evaluated the application with 11 adult participants using scenario-based tasks and questionnaire feedback.

The evaluation focused on authentication, memory storage and recall, AI responses, chat history, and the Clear Chat and Clear Memory controls.

* Memory storage and recall: 5.00/5
* Overall PulsePet concept: 4.64/5

## Technologies

* Python
* Flask
* SQLite
* OpenAI API
* HTML and CSS
* JavaScript
* Unity and Blender for experimental avatar work

## Running locally

```bash
git clone <repository-url>
cd PulsePet

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
export OPENAI_API_KEY="your-api-key"

python app.py
```

The application requires an OpenAI API key. API keys and private configuration files should never be committed to the repository.

## Project status

The Flask and SQLite web application is the evaluated core MVP. Voice, avatar and physical-device work were explored as extensions rather than required parts of the main application.
