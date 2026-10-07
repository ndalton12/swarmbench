# ~/.profile
if [ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$PATH"
