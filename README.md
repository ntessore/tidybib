# tidybib

**A BibTeX formatter, written in Python**

The `tidybib` command takes BibTeX input files and reformats their contents.
There is no configuration; everyone gets the same boring output.

# Installation

Install `tidybib` with pip:

    % pip install tidybib

Alternatively, you can run `tidybib` using [pipx](https://pypa.github.io/pipx/)
without installation:

    % pipx run tidybib

# Usage

Run `tidybib` on BibTex files `main.bib` and `aux.bib`:

    % tidybib main.bib aux.bib

After the command has run, the contents of `main.bib` and `aux.bib` have been
reformatted in place. Copies of the original files are kept under
`main.bib.untidy` and `aux.bib.untidy` -- these will be overwritten the next
time `tidybib` runs on changed input files.

You can also run `tidybib` on standard input:

    % cat main.bib | tidybib

This will produce the formatted contents on standard output, and no files are
changed.

# Acknowledgements

All of the hard work of extracting a grammar and parser from the BibTeX source
code was done by [**aclements/biblib**](https://github.com/aclements/biblib).
