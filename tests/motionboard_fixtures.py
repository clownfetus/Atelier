"""Explicit synthetic Niagara LUTs and real binding-shaped names for isolated checks."""
import copy

ASSET = 'Fixture/NS_Motionboard'


def details():
    def export(index, channels, samples, name=None):
        return {'exportIndex': index, 'name': name or 'NiagaraDataInterfaceCurve',
                'classType': 'NiagaraDataInterfaceColorCurve' if channels == 4 else 'NiagaraDataInterfaceCurve',
                'channels': channels, 'shaderLut': {'sampleCount': len(samples), 'floatCount': len(samples)*channels,
                                                 'minTime': 0, 'maxTime': 1, 'samples': samples}}
    color = [[1-t, .15+t*.4, .2+t*.6, 1-t*.7] for t in (0, .25, .5, .75, 1)]
    return {'totalExports': 12, 'colorExports': 3, 'exports': [
        export(1, 4, color, 'ColourOverLife'), export(2, 4, copy.deepcopy(color), 'ColourClone'),
        export(3, 1, [[1], [.8], [.5], [.2], [0]], 'AlphaCurve'),
        export(4, 2, [[.2,.4], [.5,.8], [1,1.3], [1.5,1.7], [2,2.5]], 'SizeCurve'),
        export(5, 1, [[0], [.8], [1], [.7], [.2]], 'SpawnCurve'),
        export(6, 4, [[3,.2,.1,1], [4,.7,.2,1], [2,2,.4,1], [1,.3,2,1], [.1,.1,.4,1]], 'GlowCurve'),
        export(7, 3, [[-2,1,3], [0,2,2], [2,1,1]], 'UnknownVector'),
        export(8, 4, [], 'UnsupportedEmpty')]}


def bindings():
    def named(name):
        return {'source': 'binding', 'label': name.replace('.', ' · '), 'names': [name]}
    return {1: named('Sparks.ScaleColor.ColorScale'), 2: {'source':'owner','label':'Sparks · UpdateScript','names':[]},
            3: named('Sparks.ScaleColor.AlphaScale'), 4: named('Sparks.ScaleSpriteSize.Uniform Curve Sprite Scale'),
            5: named('Sparks.SpawnRate.SpawnRate'), 6: named('Sparks.Emissive.EmissiveColor'),
            7: {'source':'owner','label':'Sparks · UpdateScript','names':[]}}
