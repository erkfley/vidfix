#!/data/data/com.termux/files/usr/bin/bash
# =============================================================
#  VidFix installer for Termux
#  Usage:  bash install.sh
#  What it does:
#    1. Installs python, ffmpeg, numpy (prebuilt Termux packages)
#    2. Creates the global command:  vidfix
# =============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "${GREEN}==>${NC} $1"; }

echo ""
echo "  VidFix installer (Termux)"
echo "  -------------------------"

# --- 1. dependencies -------------------------------------------------------
step "Installing dependencies (python, ffmpeg, numpy)..."
pkg install -y python ffmpeg python-numpy termux-tools >/dev/null

# --- 2. resolve project dir ------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 3. create the global command $PREFIX/bin/vidfix -----------------------
step "Creating command: vidfix"
mkdir -p "$PREFIX/bin"
cat > "$PREFIX/bin/vidfix" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
exec python "$SCRIPT_DIR/app.py" "\$@"
EOF
chmod +x "$PREFIX/bin/vidfix"

# --- 4. verify --------------------------------------------------------------
step "Verifying..."
python -c "import numpy" 2>/dev/null || {
    echo -e "${YELLOW}numpy missing, trying pip fallback...${NC}"
    pip install numpy
}
ffmpeg -version | head -n 1
python --version

echo ""
echo -e "${GREEN}Done!${NC} Start enhancing videos with:"
echo ""
echo "    vidfix                 (interactive menu)"
echo "    vidfix video.mp4       (quick mode, defaults: 1080p / auto-fix / 60fps)"
echo ""
