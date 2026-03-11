"""Package entry point for the Jira worklog reporting CLI."""

from jirareport.interfaces.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
