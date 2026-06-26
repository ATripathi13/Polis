#!/bin/bash
# Pre-commit hook to prevent print() calls
# Install to .git/hooks/pre-commit

set -e

echo "🔍 Checking for forbidden print() statements..."

# Find all Python files
python_files=$(find polis -name "*.py" -type f 2>/dev/null || true)

if [ -z "$python_files" ]; then
    echo "✓ No Python files found"
    exit 0
fi

# Check for print( calls (but allow in comments)
violations=$(echo "$python_files" | xargs grep -n "print(" 2>/dev/null | \
    grep -v "# print" | \
    grep -v "\".*print" | \
    grep -v "'.*print" || true)

if [ -n "$violations" ]; then
    echo "❌ VIOLATION: print() calls detected:"
    echo "$violations"
    echo ""
    echo "RULE: No print() calls allowed in Polis."
    echo "Use ContextLogger instead:"
    echo ""
    echo "  from infrastructure.logging import ContextLogger"
    echo "  logger = ContextLogger('engine_name', correlation_id='...')"
    echo "  logger.info('Message', operation='...')"
    echo ""
    exit 1
fi

# Check for sys.stdout.write() calls
violations=$(echo "$python_files" | xargs grep -n "sys\.stdout\.write" 2>/dev/null || true)

if [ -n "$violations" ]; then
    echo "❌ VIOLATION: sys.stdout.write() calls detected:"
    echo "$violations"
    echo ""
    echo "RULE: No direct stdout writes allowed in Polis."
    echo "Use ContextLogger instead."
    echo ""
    exit 1
fi

# Check for sys.stderr.write() calls
violations=$(echo "$python_files" | xargs grep -n "sys\.stderr\.write" 2>/dev/null || true)

if [ -n "$violations" ]; then
    echo "❌ VIOLATION: sys.stderr.write() calls detected:"
    echo "$violations"
    echo ""
    echo "RULE: No direct stderr writes allowed in Polis."
    echo "Use ContextLogger instead."
    echo ""
    exit 1
fi

echo "✓ No forbidden print() or output calls found"
exit 0
