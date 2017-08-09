# svg2cutplotter

send SVG files to a cut plotter using python3. supports:
- HPGL and DPML languages
- scaling
- previewing the boundaries
- overcuts
- offsets

This script was created after being frustrated by the inkcut plugin for Inkscape.
It's not perfect and does not strive to be well coded but just be less frustrating for me.
I hope it can help you, too :)

This tool does not support curves in your SVG file.
Inkscape can remove them using Plugins → Modifiy Path → Straighten Bezier Curves.

## Installing Dependencies

```
pip3 install -r requirements.txt
```

## Usage

call `python3 svg2cutplotter.py <svg filename>`. you will get a command shell.
type `help` there for a list of commands.

call `svg2cutplotter -h` to see how to set options directly from the command line.
