"""Checkout-friendly entry point for the Arline web shutdown CLI."""

from src.cli.shutdown import main


if __name__ == "__main__":
    raise SystemExit(main())
