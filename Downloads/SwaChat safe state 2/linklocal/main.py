import sys

from linklocal.cli import cli


if __name__ == "__main__":
    if len(sys.argv) == 1:
        cli.main(args=["start", "--gui"], prog_name="main.py")
    else:
        cli()
