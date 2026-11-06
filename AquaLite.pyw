# Aqua Lite - hold Ctrl+Win, speak, release: polished text appears wherever your cursor is.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from aqualite import selftest
        sys.exit(selftest.main())
    from aqualite.app import main
    main()
