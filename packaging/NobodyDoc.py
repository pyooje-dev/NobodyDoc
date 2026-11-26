"""Point d'entrée de l'exécutable Windows."""

import sys

if "--auto-test" in sys.argv:
    from nobodydoc.selftest import main as selftest

    sys.exit(selftest(sys.argv))

from nobodydoc.gui.app import main

sys.exit(main())
