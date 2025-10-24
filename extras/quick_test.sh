#!/bin/bash

echo "🧪 Running Quick System Test..."
echo ""

if [ ! -f "system_test.py" ]; then
    echo "❌ system_test.py not found!"
    exit 1
fi

python system_test.py

echo ""
echo "=================================="
echo "Next Steps:"
echo "=================================="
echo ""
echo "If tests passed, try joining a meeting:"
echo "  python debug_bot.py 'https://meet.google.com/wni-yibm-pyu'"
echo ""
echo "Or start the server:"
echo "  python server.py"
echo ""
