#!/bin/bash
# =============================================================================
# setup.sh - Install and initialize iPhone-15plus-Tools
# =============================================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
MAIN_SCRIPT="dr_iphone.py"
BASHRC="$HOME/.bashrc"

cd "$REPO_DIR"

# 1️⃣ Create virtual environment if missing
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "[+] Virtual environment created at $VENV_DIR"
fi

# 2️⃣ Activate virtual environment
source "$VENV_DIR/bin/activate"

# 3️⃣ Upgrade pip
pip install --upgrade pip

# 4️⃣ Install dependencies
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
    echo "[+] Dependencies installed from requirements.txt"
fi

# 5️⃣ Ensure pymobiledevice3 is installed
pip install --upgrade pymobiledevice3

# 6️⃣ Set PMD3_CLI environment variable permanently if not already
if ! grep -q "PMD3_CLI" "$BASHRC"; then
    echo "export PMD3_CLI=\$VIRTUAL_ENV/bin/pymobiledevice3" >> "$BASHRC"
    echo "[+] Added PMD3_CLI to $BASHRC"
fi

# Also export for current session
export PMD3_CLI="$VENV_DIR/bin/pymobiledevice3"

# 7️⃣ Make main script executable
chmod +x "$MAIN_SCRIPT"

# 8️⃣ Verify installation
echo "[+] Running $MAIN_SCRIPT --help for verification..."
python "$MAIN_SCRIPT" --help || echo "[!] --help run failed, check script"

# 9️⃣ Summary
echo "[+] Setup complete."
echo "[+] Virtual environment: $VENV_DIR"
echo "[+] PMD3_CLI set to: $PMD3_CLI"
echo "[+] Activate in future sessions with: source $VENV_DIR/bin/activate"
