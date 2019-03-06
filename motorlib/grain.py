from . import geometry
from . import units
from .properties import *

import numpy as np
import skfmm
from skimage import measure

class grain(propertyCollection):
    geomName = None
    def __init__(self):
        super().__init__()
        self.props['diameter'] = floatProperty('Diameter', 'm', 0, 1)
        self.props['length'] = floatProperty('Length', 'm', 0, 2)

    def getVolumeSlice(self, r, dR):
        return self.getVolumeAtRegression(r) - self.getVolumeAtRegression(r + dR)

    def getSurfaceAreaAtRegression(self, r):
        return None
    
    def getVolumeAtRegression(self, r):
        return None

    def getWebLeft(self, r): # Returns the shortest distance the grain has to regress to burn out
        return None

    def isWebLeft(self, r, burnoutThres = 0.00001):
        return self.getWebLeft(r) > burnoutThres

    def getMassFlux(self, massIn, dt, r, dr, position, density):
        return None

    def getPeakMassFlux(self, massIn, dt, r, dr, density):
        return self.getMassFlux(massIn, dt, r, dr, self.getEndPositions(r)[1], density) # Assumes that peak mass flux for each grain is at the port of the grain

    def getEndPositions(self, r): # Returns the positions of the grain ends relative to the original (unburned) grain top
        return None

    def getPortArea(self, r):
        return None

    def getRegressedLength(self, r):
        endPos = self.getEndPositions(r)
        return endPos[1] - endPos[0]

    def getDetailsString(self, preferences):
        return 'Length: ' + self.props['length'].dispFormat(preferences.units.getProperty('m'))


def length(contour): # Adds up the length of each segment in a contour
    offset = np.roll(contour.T, 1, axis = 1)
    l = np.linalg.norm(contour.T - offset, axis = 0)
    return sum(list(l)[1:])

def clean(contour, m = 498): # Removes the points in a contour near the edge (inhibits the casting tube)
    offset = np.array([[500, 500]])
    l = np.linalg.norm(contour - offset, axis = 1)
    return contour[l < m]


class perforatedGrain(grain):
    geomName = 'PerfGrain'
    def __init__(self):
        super().__init__()
        self.props['inhibitedEnds'] = enumProperty('Inhibited ends', ['Neither', 'Top', 'Bottom', 'Both'])

        self.mapDim = 1001
        self.X, self.Y = None, None
        self.mask = None
        self.coreMap = None
        self.regressionMap = None
        self.wallWeb = 0 # Max distance from the core to the wall

    def getEndPositions(self, r):
        # Until there is some kind of enum prop, inhibited faces are handled like this:
        if self.props['inhibitedEnds'].getValue() == 'Neither': # Neither
            return [r, self.props['length'].getValue() - r]
        elif self.props['inhibitedEnds'].getValue() == 'Top': # Top
            return [0, self.props['length'].getValue() - r]
        elif self.props['inhibitedEnds'].getValue() == 'Bottom': # Bottom
            return [r, self.props['length'].getValue()]
        elif self.props['inhibitedEnds'].getValue() == 'Both':
            return [0, self.props['length'].getValue()]

    def normalize(self, value): # Used when transforming real unit quantities into self.X, self.Y coordinates
        return value / (0.5 * self.props['diameter'].getValue())

    def unNormalize(self, value): # Used to transform self.X, self.Y coordinates to real unit quantities
        return (value / 2) * self.props['diameter'].getValue()

    def lengthToMap(self, value): # Used to convert meters to pixels
        return self.mapDim * (value / self.props['diameter'].getValue())

    def mapToLength(self, value): # Used to convert pixels to meters
        return self.props['diameter'].getValue() * (value / self.mapDim)

    def areaToMap(self, value): # Used to convert sqm to sq pixels
        return (self.mapDim ** 2) * (value / (self.props['diameter'].getValue() ** 2))

    def mapToArea(self, value): # Used to convert sq pixels to sqm
        return (self.props['diameter'].getValue() ** 2) * (value / (self.mapDim ** 2))

    def initGeometry(self):
        self.X, self.Y = np.meshgrid(np.linspace(-1, 1, self.mapDim), np.linspace(-1, 1, self.mapDim))
        self.mask = self.X**2 + self.Y**2 > 1
        self.coreMap = np.ones_like(self.X)

    def generateCoreMap(self):
        pass

    def generateRegressionMap(self):
        self.initGeometry()
        self.generateCoreMap()
        masked = np.ma.MaskedArray(self.coreMap, self.mask)
        #plt.imshow(masked)
        #plt.show()
        self.regressionMap = skfmm.distance(masked, dx=1e-3) * 2
        self.wallWeb = self.unNormalize(np.amax(self.regressionMap))
        #plt.imshow(self.regressionMap)
        #plt.show()

    def getCorePerimeter(self, r):
        if self.regressionMap is None:
            self.generateRegressionMap()

        mapDist = self.normalize(r)

        corePerimeter = 0
        contours = measure.find_contours(self.regressionMap, mapDist, fully_connected='high')
        for contour in contours:
            contour = clean(contour)
            corePerimeter += self.mapToLength(length(contour))

        return corePerimeter

    def getCoreSurfaceArea(self, r):
        corePerimeter = self.getCorePerimeter(r)
        coreArea = corePerimeter * self.getRegressedLength(r)
        return coreArea

    def getFaceArea(self, r):
        if self.regressionMap is None:
            self.generateRegressionMap()

        mapDist = self.normalize(r)

        valid = np.logical_not(self.mask)
        faceArea = self.mapToArea(np.count_nonzero(np.logical_and(self.regressionMap > mapDist, valid)))

        return faceArea

    def getWebLeft(self, r):
        if self.regressionMap is None:
            self.generateRegressionMap()

        wallLeft = self.wallWeb - r
        lengthLeft = self.getRegressedLength(r)

        return min(lengthLeft, wallLeft)

    def getSurfaceAreaAtRegression(self, r):
        faceArea = self.getFaceArea(r)
        coreArea = self.getCoreSurfaceArea(r)

        exposedFaces = 2
        if self.props['inhibitedEnds'].getValue() == 'Top' or self.props['inhibitedEnds'].getValue() == 'Bottom':
            exposedFaces = 1
        if self.props['inhibitedEnds'].getValue() == 'Both':
            exposedFaces = 0

        return coreArea + (exposedFaces * faceArea)
    
    def getVolumeAtRegression(self, r):
        faceArea = self.getFaceArea(r)
        return faceArea * self.getRegressedLength(r)

    def getPortArea(self, r):
        faceArea = self.getFaceArea(r)
        uncored = geometry.circleArea(self.props['diameter'].getValue())
        return uncored - faceArea

    def getMassFlux(self, massIn, dt, r, dr, position, density): # This duplicates a lot of code from bates. Time to make bates a perforated grain?
        diameter = self.props['diameter'].getValue()

        bLength = self.getRegressedLength(r)
        endPos = self.getEndPositions(r)

        if position < endPos[0]: # If a position above the top face is queried, the mass flow is just the input mass and the diameter is the casting tube
            return massIn / geometry.circleArea(diameter)
        elif position <= endPos[1]: # If a position in the grain is queried, the mass flow is the input mass, from the top face, and from the tube up to the point. The diameter is the core.
            if self.props['inhibitedEnds'].getValue() == 'Top': # Top inhibited
                top = 0
                countedCoreLength = position
            else:
                top = self.getFaceArea(r + dr) * dr * density
                countedCoreLength = position - (endPos[0] + dr)
            core = ((self.getPortArea(r + dr) * countedCoreLength) - (self.getPortArea(r) * countedCoreLength)) * density
            mf = massIn + ((top + core) / dt)
            return mf / self.getPortArea(r + dr)
        else: # A poition past the grain end was specified, so the mass flow includes the input mass flow and all mass produced by the grain. Diameter is the casting tube.
            mf = massIn + (self.getVolumeSlice(r, dr) * density / dt)
            return mf / geometry.circleArea(diameter)
