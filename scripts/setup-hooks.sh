#!/bin/bash
# Setup pre-commit hooks for Polis

set -e

echo "Setting up pre-commit hooks..."

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo "❌ Not in a git repository. Aborting."
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p .git/hooks

# Copy pre-commit hook
echo "📝 Installing pre-commit hook..."
cp scripts/pre-commit-check-print.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

echo "✓ Pre-commit hook installed"
echo ""
echo "The following checks will run before each commit:"
echo "  - Scan for print() calls"
echo "  - Scan for sys.stdout.write() calls"
echo "  - Scan for sys.stderr.write() calls"
echo ""
echo "To bypass hooks (not recommended):"
echo "  git commit --no-verify"
echo ""
echo "✓ Setup complete"
