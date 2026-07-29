#!/bin/bash
#
# Manim Quick Installer for Google Colab
#

set -e

show_help() {
    cat <<EOF
🚀 Manim Quick Installer for Google Colab

Usage: curl -sL https://get.manim.community/colab.sh | bash [OPTIONS]

Options:
  --vscode         Install and start VS Code server
  --version X.Y.Z  Install specific Manim version (default: latest)
  --tex            Install TinyTeX (lightweight LaTeX distribution)
  --help           Show this help message

Examples:
  # Basic installation
  curl -sL https://get.manim.community/colab.sh | bash

  # With VS Code server
  curl -sL https://get.manim.community/colab.sh | bash -s -- --vscode

  # Full installation with LaTeX
  curl -sL https://get.manim.community/colab.sh | bash -s -- --tex --vscode

  # Specific Manim version
  curl -sL https://get.manim.community/colab.sh | bash -s -- --version 0.19.0
EOF
    exit 0
}

# Parse arguments
INSTALL_VSCODE=false
INSTALL_TEX=false
MANIM_VERSION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            show_help
            ;;
        --vscode)
            INSTALL_VSCODE=true
            shift
            ;;
        --version)
            MANIM_VERSION="$2"
            shift 2
            ;;
        --tex)
            INSTALL_TEX=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "🚀 Manim Installer for Google Colab"
echo "===================================="

# Check if running in Colab
if [ -d "/content" ] && command -v ipython &> /dev/null; then
    echo "✓ Detected Google Colab environment"
else
    echo "⚠️  Warning: This script is designed for Google Colab"
fi

# Install system dependencies
echo "📦 Installing system dependencies..."
sudo apt-get -qq update 2>/dev/null
sudo apt-get -qq install -y \
    build-essential \
    python3-dev \
    libcairo2-dev \
    libpango1.0-dev \
    ffmpeg \
    2>&1 | grep -v "^debconf:" | grep -v "^dpkg-preconfigure:" | grep -v "^W:" || true

# Install TinyTeX (optional)
if [ "$INSTALL_TEX" = true ]; then
    if [ -d "$HOME/.TinyTeX" ]; then
        echo "✓ TinyTeX already installed"
    else
        echo "📥 Installing TinyTeX (lightweight LaTeX)..."
        curl -sSL https://yihui.org/tinytex/install-bin-unix.sh | sh > /dev/null 2>&1
        
        # Pre-install Manim's required packages
        echo "   Installing LaTeX packages for Manim..."
        ~/bin/tlmgr install \
            amsmath babel-english cbfonts-fd cm-super ctex doublestroke dvisvgm \
            everysel fontspec frcursive fundus-calligra gnu-freefont jknapltx \
            latex-bin mathastext microtype multitoc physics preview prelim2e \
            ragged2e relsize rsfs setspace standalone tipa wasy wasysym xcolor \
            xetex xkeyval > /dev/null 2>&1 || true
        
        echo "✓ TinyTeX installed"
    fi
fi

# Install Manim
echo "🐍 Installing Manim..."
if [ -n "$MANIM_VERSION" ]; then
    pip install -q --disable-pip-version-check --no-warn-script-location "manim==$MANIM_VERSION" 2>/dev/null
else
    pip install -q --disable-pip-version-check --no-warn-script-location manim 2>/dev/null
fi

# Install and start VS Code server (optional)
if [ "$INSTALL_VSCODE" = true ]; then
    if [ ! -f "/usr/local/bin/code" ]; then
        echo "📥 Installing VS Code server..."
        curl -sSL https://update.code.visualstudio.com/latest/cli-linux-x64/stable -o /tmp/vscode_cli.tar.gz
        sudo tar -xzf /tmp/vscode_cli.tar.gz -C /usr/local/bin/
        rm /tmp/vscode_cli.tar.gz
    fi
    echo "✓ VS Code server installed"
    echo ""
    echo "🔗 Starting tunnel... (click the link to connect)"
    echo "================================================"
    /usr/local/bin/code tunnel --accept-server-license-terms
else
    # Only show completion message if not starting VS Code tunnel
    echo ""
    echo "✅ Installation complete!"
    echo "========================"
    echo ""
    echo "Try it out:"
    echo "  manim --version"
    if [ "$INSTALL_TEX" = true ]; then
        echo ""
        echo "📝 TinyTeX: missing packages auto-install on first use"
    fi
    echo ""
    echo "Happy Manimating! 🎬"
fi
