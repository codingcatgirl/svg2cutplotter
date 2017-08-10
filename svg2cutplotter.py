import argparse
import os
import re
from operator import itemgetter

import defusedxml.ElementTree as ET
from shapely.affinity import translate, scale
from shapely.geometry import MultiLineString, LineString, box

def check_float(value):
    value = float(value)
    if value <= 0.0:
        raise TypeError('Scaling has to be > 0.0')
    return value


parser = argparse.ArgumentParser(description='Plot SVG images.')
parser.add_argument('filename', type=str, nargs=1, help='svg file')
parser.add_argument('--device', type=str, help='device path (e.g. /dev/ttyUSB0)')
parser.add_argument('--language', type=str, choices=('hpgl', 'dpml'), help='plotter language')
parser.add_argument('--scaling', type=check_float, default=1.0, help='scaling (default 1.0)')
parser.add_argument('--offsetx', type=float, default=0.0, help='x offset in mm (default 0.0mm)')
parser.add_argument('--offsety', type=float, default=0.0, help='y offset in mm (default 0.0mm)')
parser.add_argument('--overcut', type=float, default=0.0, help='overcut in mm (default 1.0mm)')
parser.add_argument('--nomirror', dest='mirror', action='store_const', const=False, default=True,
                    help='do not mirror the y axis')
args = parser.parse_args()

tree = ET.parse(args.filename[0])
root = tree.getroot()

viewbox = root.attrib['viewBox'].split(' ')
width = float(re.match('^[0-9]+(\.[0-9]+)?mm', root.attrib['width']).group(0)[:-2])
height = float(re.match('^[0-9]+(\.[0-9]+)?mm', root.attrib['height']).group(0)[:-2])
if width > height:
    scaling = width / float(viewbox[2])
else:
    scaling = height / float(viewbox[3])

namespaces = {'svg': 'http://www.w3.org/2000/svg'}

def parse_svg_data(data):
    first = False

    last_point = (0, 0)
    last_end_point = None

    done_subpaths = []
    current_subpath = []
    while data:
        data = data.lstrip().replace(',', ' ')
        command = data[0]
        if first and command not in 'Mm':
            raise ValueError('path data has to start with moveto command.')
        data = data[1:].lstrip()
        first = False

        numbers = []
        while True:
            match = re.match('^-?[0-9]+(\.[0-9]+)?', data)
            if match is None:
                break
            numbers.append(float(match.group(0)))
            data = data[len(match.group(0)):].lstrip()

        relative = command.islower()
        if command in 'Mm':
            if not len(numbers) or len(numbers) % 2:
                raise ValueError('Invalid number of arguments for moveto command!')
            numbers = iter(numbers)
            for x, y in zip(numbers, numbers):
                if relative:
                    x, y = last_point[0]+x, last_point[1]+y
                if current_subpath:
                    done_subpaths.append(current_subpath)
                    last_end_point = current_subpath[-1]
                    current_subpath = []
                current_subpath.append((x, y))
                last_point = (x, y)

        elif command in 'Ll':
            if not len(numbers) or len(numbers) % 2:
                raise ValueError('Invalid number of arguments for lineto command!')
            numbers = iter(numbers)
            for x, y in zip(numbers, numbers):
                if relative:
                    x, y = last_point[0]+x, last_point[1]+y
                if not current_subpath:
                    current_subpath.append(last_end_point)
                current_subpath.append((x, y))
                last_point = (x, y)

        elif command in 'Hh':
            if not len(numbers):
                raise ValueError('Invalid number of arguments for horizontal lineto command!')
            y = last_point[1]
            for x in numbers:
                if relative:
                    x = last_point[0]+x
                if not current_subpath:
                    current_subpath.append(last_end_point)
                current_subpath.append((x, y))
                last_point = (x, y)

        elif command in 'Vv':
            if not len(numbers):
                raise ValueError('Invalid number of arguments for vertical lineto command!')
            x = last_point[0]
            for y in numbers:
                if relative:
                    y = last_point[1]+y
                if not current_subpath:
                    current_subpath.append(last_end_point)
                current_subpath.append((x, y))
                last_point = (x, y)

        elif command in 'Zz':
            if numbers:
                raise ValueError('Invalid number of arguments for closepath command!')
            current_subpath.append(current_subpath[0])
            done_subpaths.append(current_subpath)
            last_end_point = current_subpath[-1]
            current_subpath = []

        else:
            raise ValueError('unknown svg command: '+command)

    if current_subpath:
        done_subpaths.append(current_subpath)
    return done_subpaths

for element in tree.findall('.//svg:clipPath/..', namespaces):
    for clippath in element.findall('./svg:clipPath', namespaces):
        element.remove(clippath)

paths = []
for element in tree.findall('.//svg:path', namespaces):
    paths.extend(parse_svg_data(element.attrib['d']))
paths, maxx = zip(*sorted(((path, LineString(path).bounds[2]) for path in paths), key=itemgetter(1)))
paths = MultiLineString(paths)
paths = scale(paths, scaling, scaling, origin=(0, 0))
if args.mirror:
    paths = scale(paths, 1, -1)



def apply_overcut(geometry, overcut):
    if geometry.is_empty:
        paths = []
    elif isinstance(geometry, LineString):
        paths = [geometry]
    elif isinstance(geometry, MultiLineString):
        paths = geometry.geoms
    else:
        raise ValueError('unknown geometry:', geometry)

    coords = []
    for path in paths:
        path_coords = list(path.coords)

        segment = LineString(path_coords[:2])
        factor = (segment.length+overcut)/segment.length
        path_coords[0] = scale(segment, xfact=factor, yfact=factor, origin=path_coords[1]).coords[0]

        segment = LineString(path_coords[-2:])
        factor = (segment.length + overcut) / segment.length
        path_coords[-1] = scale(segment, xfact=factor, yfact=factor, origin=path_coords[-2]).coords[-1]

        coords.append(path_coords)

    return MultiLineString(coords)


def plot_data(geometry, pen_down=False, dpml=False, offsetx=0, offsety=0, overcut=0):
    if geometry.is_empty:
        paths = []
    elif isinstance(geometry, LineString):
        paths = [geometry]
    elif isinstance(geometry, MultiLineString):
        paths = geometry.geoms
    else:
        raise ValueError('unknown geometry:', geometry)

    output = 'IN;SP1;'
    for path in paths:
        first = True
        for x, y in path.coords:
            output += '%s%d,%d;' % ('PD' if not first and pen_down else 'PU',
                                    max(0, round(x*40)), max(0, round(y*40)))
            if first:
                first = False
    output += 'PU%d,%d;IN;' % (round(offsetx), round(offsety))

    if dpml:
        output = output.replace("IN;", " ;:H A L0 ", 1)
        output = output.replace(";VS", " V", 1)  # setting velocity
        output = output.replace(" SP1", " EC1", 1)  # specify pen
        output = output.replace(";IN;", " @ ", 1)
        output = output.replace(";PD", " D")
        output = output.replace(";PU", " U")

    return output


bounds = paths.bounds
width = bounds[2]-bounds[0]
height = bounds[3]-bounds[1]

scaling = args.scaling
offsetx = args.offsetx
offsety = args.offsety
overcut = args.overcut
if args.device is not None:
    device = args.device
else:
    try:
        device = '/dev/'+next(file for file in os.listdir('/dev/') if file.startswith('ttyUSB'))
    except StopIteration:
        device = '/dev/ttyUSB0'
language = args.language


show = True
help_hint = True
while True:
    if show:
        print()
        print('Path:      width: %.2fmm  height %.2fmm' % (width, height))
        print('Settings:  scaling: %.3f  offset x: %.2fmm  offset y: %.2fmm  overcut: %.2fmm' %
              (scaling, offsetx, offsety, overcut))
        print('Plot:      minx: %.2fmm  miny: %.2fmm  maxx: %.2fmm  maxy: %.2fmm' %
              ((offsetx)*scaling, (offsetx+width)*scaling, (offsety)*scaling, (offsety+height)*scaling))
        print('Device:    device: %s  language: %s' % (device, language))
        show = False

    print()
    if help_hint:
        print('Type "help" for help')
        help_hint = False

    command = input('>>> ').lower()
    if command in ('help', 'h'):
        print('help      print this help')
        print('show      show graph data / settings')
        print('scale     set scale')
        print('offsetx   set offset x')
        print('offsety   set offset y')
        print('overcut   set overcut')
        print('device    set device')
        print('language  set language')
        print('bounds    show bouds on plotter')
        print('plot      plot')

    elif command in ('show', 's'):
        show = True
    elif command in ('scaling', 'offsetx', 'offsety', 'overcut'):
        data = input('Enter %s as float: ' % command)
        try:
            data = float(data)
        except ValueError:
            print('Invalid value.')
        else:
            if command in ('scale', 'overcut') and data <= 0:
                print('%s has to be > 0.' % command)
            else:
                locals()[command] = data
                print('%s set!' % command)
                show = True
    elif command == 'device':
        data = input('Enter device as absolute path: ').strip()
        if data:
            device = data
            print('Device set.')
        else:
            print('Invalid device.')
    elif command == 'language':
        data = input('Enter language (hpgl or dpml): ').strip()
        if data in ('hpgl', 'dpml'):
            language = data
            print('Language set.')
        else:
            print('Invalid language.')
    elif command == 'bounds':
        if language is None:
            print('Language not set.')
        else:
            bounds_path = LineString(((0, 0), (width, 0), (width, height), (0, height), (0, 0)))
            bounds_path = scale(translate(bounds_path, xoff=offsetx, yoff=offsety), scaling, scaling, origin=(0, 0))
            open(device, 'w').write(plot_data(bounds_path, dpml=(language == 'dpml')))
    elif command == 'plot':
        if language is None:
            print('Language not set.')
        else:
            plot_paths = paths
            plot_paths = apply_overcut(plot_paths, overcut=overcut)
            plot_paths = translate(plot_paths, xoff=0-bounds[0], yoff=0-bounds[1])
            plot_paths = scale(translate(plot_paths, xoff=offsetx, yoff=offsety), scaling, scaling, origin=(0, 0))
            open(device, 'w').write(plot_data(plot_paths, dpml=(language == 'dpml'),
                                              pen_down=True, offsetx=offsetx, offsety=offsety))
    else:
        print('Unknown command!')



