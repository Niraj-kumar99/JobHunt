"""Command line:  python -m jobbot run | check "Company" """
import argparse

from .run import check_company, run


def main():
    p = argparse.ArgumentParser(prog="jobbot", description="Scrape European careers pages for entry-level PM/BA jobs.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scan all companies and write the reports")
    r.add_argument("--only", nargs="*", help="scan only these companies (exact names from companies.csv)")
    r.add_argument("--limit", type=int, help="scan only the first N companies (for a quick test)")
    c = sub.add_parser("check", help="debug one company without changing saved state")
    c.add_argument("company")
    a = p.parse_args()
    if a.cmd == "run":
        run(only=a.only, limit=a.limit)
    else:
        check_company(a.company)


if __name__ == "__main__":
    main()
