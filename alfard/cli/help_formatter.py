"""Custom Click help formatter — applies alfard palette to all --help output."""

import click
from alfard.cli.theme import p, c

RULE = "─" * 44


class AlfardHelpFormatter(click.HelpFormatter):

    def write_usage(self, prog, args="", prefix="usage"):
        self.write(f"\n  {c('fg_faint', 'usage')}   "
                   f"{c('fg_em', prog)} {c('fg_dim', args)}\n\n")

    def write_heading(self, heading):
        self.write(f"\n  {c('fg_faint', heading.upper())}\n"
                   f"  {c('rule', RULE)}\n")

    def write_dl(self, rows, col_max=30, col_spacing=2):
        for first, second in rows:
            self.write(f"    {c('fg_em', first.ljust(col_max))}"
                       f"  {c('fg_dim', second)}\n")
        self.write("\n")


class AlfardGroup(click.Group):

    def format_help(self, ctx, formatter):
        from alfard.cli.components import header_block
        from rich.console import Console
        Console().print(header_block())
        super().format_help(ctx, formatter)

    def make_formatter(self):
        return AlfardHelpFormatter()


class AlfardCommand(click.Command):

    def make_formatter(self):
        return AlfardHelpFormatter()
