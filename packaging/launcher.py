"""PyInstaller entry point."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mathdraw.app import main

    main()
