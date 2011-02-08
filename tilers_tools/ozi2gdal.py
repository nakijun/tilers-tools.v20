#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 2011-02-08 15:42:24 

###############################################################################
# Copyright (c) 2010, Vadim Shlyakhov
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#******************************************************************************

from __future__ import with_statement

import os
import logging
import locale
import csv

from optparse import OptionParser

from tiler_functions import *
from translate2gdal import *

class OziMap(MapTranslator):

    def __init__(self,src_file,options=None):
        self.init_data()
        super(OziMap,self).__init__(src_file,options)

    proj_parms=( 
        '+lat_0=', # 1. Latitude Origin
        '+lon_0=', # 2. Longitude Origin
        '+k=',     # 3. K Factor
        '+x_0=',   # 4. False Easting
        '+y_0=',   # 5. False Northing
        '+lat_1=', # 6. Latitude 1
        '+lat_2=', # 7. Latitude 2
        '+h=',     # 8. Height - used in the Vertical Near-Sided Perspective Projection
                   # 9. Sat - not used
                   #10. Path - not used
        )
        
    def init_data(self):
        'load datum definitions, ellipses, projections from a file'
        self.datum_map={}
        self.ellps_map={}
        self.proj_map={}
        ld('sys.path[0]',sys.path[0])
        def_dir=sys.path[0]
        with open(os.path.join(def_dir,'ozi_data.csv'),'rb') as data_f:
            data_csv=csv.reader(data_f)
            csv_map={
                'datum': self.datum_map,
                'ellps': self.ellps_map,
                'proj': self.proj_map,
                }
            for row in data_csv:
                ld(row)
                try:
                    csv_map[row[0]][row[1]]=row[2:]
                except IndexError:
                    pass
                except KeyError:
                    pass
#        ld(self.datum_map)
#        ld(self.ellps_map)
#        ld(self.proj_map)

    def get_header(self): 
        'read map header'
        with open(self.map_file, 'rU') as f:
            hdr=[[i.strip() for i in l.split(',')] for l in f]
        if not (hdr and hdr[0][0].startswith('OziExplorer Map Data File')): 
            raise Exception(" Invalid file: %s" % self.map_file)
        ld(hdr)
        return hdr

    def hdr_parms(self, patt): 
        'filter header for params starting with "patt"'
        return [i for i in self.header if i[0].startswith(patt)]
        
    def get_refs(self):
        'get a list of geo refs in tuples'
        points=[i for i in self.hdr_parms('Point') if i[2] != ''] # Get a list of geo refs
        if points[0][14] != '': # refs are cartesian
            refs=[(
                (int(i[2]),int(i[3])),                  # pixel
                (),                                     # lat/long
                (float(i[14]),float(i[15])),            # cartesian coords
                i[16],                                  # hemisphere
                i[13],                                  # utm zone
                ) for i in points]
        else:
            refs=[(
                (int(i[2]),int(i[3])),                  # pixel
                (dms2dec(*i[9:12]), dms2dec(*i[6:9])),  # lat/long
                ) for i in points]
        return refs

    def get_dtm(self):
        'get DTM northing, easting'
        dtm=[float(s)/3600 for s in self.header[4][2:4]]
        return dtm if dtm != [0,0] else None

    def get_srs(self):
        options=self.options
        refs=self.refs
        dtm=None
        srs=[]
        if options.srs:
            return(self.options.srs,refs)
        if options.proj:
            srs.append(options.proj)
        else:
            proj_id=self.hdr_parms('Map Projection')[0][1]
            parm_lst=self.hdr_parms('Projection Setup')[0]
            try:
                srs.append(self.proj_map[proj_id][0])
            except KeyError: 
                raise Exception("*** Unsupported projection (%s)" % proj_id)
            if '+proj=' in srs[0]: # overwise assume it already has a full data defined
                # get projection parameters
                srs.extend([ i[0]+i[1] for i in zip(self.proj_parms,parm_lst[1:]) if i[1].translate(None,'0.')])
                if '+proj=utm' in srs[0]:
                    if not refs[0][1]: # refs are cartesian with a zone defined
                        hemisphere=refs[0][3]
                        utm_zone=int(refs[0][4])
                        srs.append('+zone=%i' % utm_zone)
                        if hemisphere != 'N': 
                            srs.append('+south')
                    else: # refs are lat/long, then find zone, hemisphere
                        # doesn't seem to have central meridian for UTM
                        lon,lat=refs[0][1]
                        zone=(lon + 3 % 360) // 6 + 30
                        srs.append('+zone=%d' % zone)
                        if lat < 0: 
                            srs.append('+south')
                else:
                    if refs[0][1]: # refs are lat/long
                        # setup a central meridian artificialy to allow charts crossing meridian 180
                        leftmost=min(refs,key=lambda r: r[0][0])
                        rightmost=max(refs,key=lambda r: r[0][0])
                        ld('leftmost',leftmost,'rightmost',rightmost)
                        if leftmost[1][0] > rightmost[1][0] and '+lon_0=' not in proj[0]:
                            srs.append(' +lon_0=%i' % int(leftmost[1][0]))
        datum_id=self.header[4][0]
        logging.info(' %s, %s' % (datum_id,proj_id))
        if options.datum: 
            datum=options.datum
        elif datum_id.startswith('Auto Shift'):
            ld(header[4])
            dtm=self.get_dtm(header) # get northing, easting to WGS84 if any
            datum='+datum=WGS84'
        else:
            try:
                datum_def=self.datum_map[datum_id]
                datum=if_set(datum_def[5]) # PROJ4 datum defined ?
                if datum:
                    srs.append(datum)
                else:
                    ellps_id=datum_def[1]
                    ellps_def=self.ellps_map[ellps_id]
                    ellps=if_set(ellps_def[2])
                    if ellps:
                        srs.append(ellps)
                    else:
                        srs.append('+a=%s',ellps_def[0])
                        srs.append('+rf=%s',ellps_def[1])                        
                    srs.append('+towgs84=%s,%s,%s' % tuple(datum_def[2:5]))
            except KeyError: 
                raise Exception("*** Unsupported datum (%s)" % datum_id)
        srs.append('+nodefs')
        ld(srs)
        return ' '.join(srs),dtm

    try_encodings=(locale.getpreferredencoding(),'utf_8','cp1251','cp1252')

    def get_raster(self):
        img_path=self.header[2][0]
        img_path_slashed=img_path.replace('\\','/') # get rid of windows separators
        img_path_lst=os.path.split(img_path_slashed)
        img_fname=img_path_lst[-1]
        map_dir,map_fname=os.path.split(self.map_file)
        dir_lst=[i.decode(locale.getpreferredencoding(),'ignore') 
                    for i in os.listdir(map_dir if map_dir else '.')]
        # try a few encodings
        for enc in self.try_encodings:
            name_patt=img_fname.decode(enc,'ignore').lower()
            match=[i for i in dir_lst if i.lower() == name_patt]
            if match:
                fn=match[0]
                ld(map_dir, fn)
                img_file=os.path.join(map_dir, fn)
                break
        else:
            raise Exception("*** Image file not found: %s" % img_path)
        return img_file

    def get_size(self):
        return map(int,self.hdr_parms( 'IWH')[0][2:])

    def get_name(self):
        ozi_name=self.header[1][0]
        # try a few encodings
        for enc in self.try_encodings:
            try:
                if enc == 'cp1251' and any([ # ascii chars ?
                        ((c >= '\x41') and (c <= '\x5A')) or 
                        ((c >= '\x61') and (c <= '\x7A')) 
                            for c in ozi_name]):
                    continue # cp1251 name shouldn't have any ascii
                ozi_name=ozi_name.decode(enc)
                break
            except:
                pass
        ld('ozi_name',ozi_name)
        return ozi_name
        
    def get_plys(self):
        'boundary polygon'
        ply_ll=[(float(i[2]),float(i[3])) for i in self.hdr_parms('MMPLL')] # Moving Map border lat,lon
        ply_pix=[(int(i[2]),int(i[3])) for i in self.hdr_parms('MMPXY')]    # Moving Map border pixels
        plys=zip(ply_pix,ply_ll)
        ld('plys',plys)
        return plys
# OziMap

def proc_src(src):
    OziMap(src,options=options).convert()

if __name__=='__main__':
    usage = "usage: %prog [--cut] [--dest-dir=DEST_DIR] MAP_file..."
    parser = OptionParser(usage=usage,
        description="Converts OziExplorer's .MAP file into GDAL .VRT format")
    parser.add_option("-d", "--debug", action="store_true", dest="debug")
    parser.add_option("-q", "--quiet", action="store_true", dest="quiet")
    parser.add_option("-t", "--dest-dir", dest="dest_dir", default='',
        help='destination directory (default: current)')
    parser.add_option("--no-data", dest="no_data", default='',
        help='set nodata masking values for input bands, separated by commas')
    parser.add_option("--expand", choices=('gray','rgb','rgba'),
        help='expose a dataset with 1 band with a color table as a dataset with 3 (RGB) or 4 (RGBA) bands')
    parser.add_option("--of",  default='VRT',
        help='Select the output format. The default is VRT')
    parser.add_option("--no-cut-file", action="store_true", 
        help='do not create a file with a cutline polygon from KAP file')
    parser.add_option("--get-cutline", action="store_true", 
        help='print cutline polygon from KAP file then exit')
    parser.add_option("--srs", default=None,
        help='override full chart with PROJ.4 definition of the spatial reference system')
    parser.add_option("--datum", default=None,
        help="override chart's datum (PROJ.4 definition)")
    parser.add_option("--proj", default=None,
        help="override chart's projection (BSB definition)")

    (options, args) = parser.parse_args()
    if not args:
        parser.error('No input file(s) specified')
    logging.basicConfig(level=logging.DEBUG if options.debug else 
        (logging.ERROR if options.quiet else logging.INFO))

    ld(os.name)
    ld(options)

    map(proc_src,args)

