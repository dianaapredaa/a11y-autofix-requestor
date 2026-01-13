#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"
PYTHON_SCRIPT="$SCRIPT_DIR/a11y-autofix.py"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "Virtual environment created at: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if ! python -c "import boto3, requests, dotenv" 2>/dev/null; then
    echo "Installing requirements..."
    pip install -r "$REQUIREMENTS"
    echo "Requirements installed successfully."
fi

echo "Running a11y-autofix.py with arguments: $@"
echo ""

python "$PYTHON_SCRIPT" "$@"

