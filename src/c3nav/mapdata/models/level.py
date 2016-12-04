from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE
from shapely.geometry import JOIN_STYLE
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.utils import assert_multipolygon


class Level(MapItem):
    """
    A map level (-1, 0, 1, 2…)
    """
    name = models.SlugField(_('level name'), unique=True, max_length=50,
                            help_text=_('Usually just an integer (e.g. -1, 0, 1, 2)'))
    altitude = models.DecimalField(_('level altitude'), null=True, max_digits=6, decimal_places=2)
    intermediate = models.BooleanField(_('intermediate level'))

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @cached_property
    def geometries(self):
        return LevelGeometries.by_level(self)

    def tofilename(self):
        return 'levels/%s.json' % self.name

    def lower(self):
        return Level.objects.filter(altitude__lt=self.altitude).order_by('altitude')

    def higher(self):
        return Level.objects.filter(altitude__gt=self.altitude).order_by('altitude')

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'altitude' not in data:
            raise ValueError('missing altitude.')

        if not isinstance(data['altitude'], (int, float)):
            raise ValueError('altitude has to be int or float.')

        kwargs['altitude'] = data['altitude']

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['altitude'] = float(self.altitude)
        return result

    def __str__(self):
        return self.name


class LevelGeometries():
    by_level_name = {}

    @classmethod
    def by_level(cls, level):
        return cls.by_level_name.setdefault(level.name, cls(level))

    def __init__(self, level):
        self.level = level

    @cached_property
    def raw_rooms(self):
        return cascaded_union([room.geometry for room in self.level.rooms.all()])

    @cached_property
    def buildings(self):
        result = cascaded_union([building.geometry for building in self.level.buildings.all()])
        if self.level.intermediate:
            result = cascaded_union([result, self.raw_rooms])
        return result

    @cached_property
    def rooms(self):
        return self.raw_rooms.intersection(self.buildings)

    @cached_property
    def outsides(self):
        return cascaded_union([outside.geometry for outside in self.level.outsides.all()]).difference(self.buildings)

    @cached_property
    def mapped(self):
        return cascaded_union([self.buildings, self.outsides])

    @cached_property
    def obstacles(self):
        return cascaded_union([obstacle.geometry for obstacle in self.level.obstacles.all()]).intersection(self.mapped)

    @cached_property
    def raw_doors(self):
        return cascaded_union([door.geometry for door in self.level.doors.all()]).intersection(self.mapped)

    @cached_property
    def elevatorlevels(self):
        return cascaded_union([elevatorlevel.geometry for elevatorlevel in self.level.elevatorlevels.all()])

    @cached_property
    def areas(self):
        return cascaded_union([self.rooms, self.outsides, self.elevatorlevels])

    @cached_property
    def holes(self):
        return cascaded_union([holes.geometry for holes in self.level.holes.all()]).intersection(self.areas)

    @cached_property
    def accessible(self):
        return self.areas.difference(self.holes).difference(self.obstacles)

    @cached_property
    def buildings_with_holes(self):
        return self.buildings.difference(self.holes)

    @cached_property
    def areas_and_doors(self):
        return cascaded_union([self.areas, self.raw_doors])

    @cached_property
    def walls(self):
        return self.buildings.difference(self.areas_and_doors)

    @cached_property
    def walls_shadow(self):
        return self.walls.buffer(0.2, join_style=JOIN_STYLE.mitre).intersection(self.buildings_with_holes)

    @cached_property
    def doors(self):
        return self.raw_doors.difference(self.areas)

    def get_levelconnectors(self, to_level=None):
        queryset = self.level.levelconnectors.prefetch_related('levels')
        print(to_level)
        if to_level is not None:
            queryset = queryset.filter(levels=to_level)
        for item in queryset:
            print(item.levels)
        return cascaded_union([levelconnector.geometry for levelconnector in queryset])

    @cached_property
    def levelconnectors(self):
        return self.get_levelconnectors()

    def intermediate_shadows(self, to_level=None):
        rings = []
        for polygon in assert_multipolygon(self.buildings):
            rings.append(polygon.exterior)
            rings.extend(polygon.interiors)

        objects = []
        levelconnectors = self.get_levelconnectors(to_level)
        for ring in rings:
            objects.append(ring.difference(levelconnectors))
        lines = cascaded_union(objects)

        return lines.buffer(0.1, cap_style=CAP_STYLE.flat, join_style=JOIN_STYLE.mitre)
