# -*- coding: utf-8 -*-
"""
hdfio.py
=========

HDF I/O for reading and writing to HDF5 files.
"""

import pyfits as pf
import numpy as np
import h5py


from ..idi import *
from .. import idi
import hdfcompress as bs
from fitsio import restricted_table_keywords, restricted_header_keywords

from ..printlog import PrintLog

restricted_hdf_keywords = {'CLASS', 'SUBCLASS', 'POSITION'}

def write_headers(hduobj, idiobj, verbosity=0):
    """ copy headers over from idiobj to hduobj.

    Need to skip values that refer to columns (TUNIT, TDISP), as
    these are necessarily generated by the table creation

    hduobj: HDF5 group
    idiobj: IDI object

    TODO: FITS header cards have to be written in correct order.
    TODO: Need to do this a little more carefully
    """

    pp = PrintLog(verbosity=verbosity)

    for key, value in idiobj.header.items():
        pp.debug(type(value))
        pp.debug("Adding header %s > %s" % (key, value))
        try:
            comment = idiobj.header[key+"_COMMENT"]
        except:
            comment = ''

        is_comment = key.endswith("_COMMENT")
        is_table   = key[:5] in restricted_table_keywords
        is_table = is_table or key[:4] == "TDIM" or key == "TFIELDS"
        is_basic = key in restricted_header_keywords
        is_hdf   = key in restricted_hdf_keywords
        if is_comment or is_table or is_basic or is_hdf:
            pass
        else:
            hduobj.attrs[key] = np.array([value])
            hduobj.attrs[key+"_COMMENT"] = np.array([comment])
    return hduobj

def read_hdf(infile, mode='r+', verbosity=0):
    """ Read and load contents of an HDF file """

    hdulist = idi.IdiHdulist()
    h = h5py.File(infile, mode=mode)
    hdulist.hdf = h

    pp = PrintLog(verbosity=verbosity)
    pp.debug(h.items())

    # See if this is a HDFITS file. Raise warnings if not, but still try to read
    cls = "None"
    try:
        cls = h.attrs["CLASS"]
    except KeyError:
        pp.warn("No CLASS defined in HDF5 file.")

    if "HDFITS" not in cls:
        pp.warn("CLASS %s: Not an HDFITS file." % cls[0])


    # Read the order of HDUs from file
    hdu_order = {}
    for gname in h.keys():
        pos = h[gname].attrs["POSITION"][0]
        hdu_order[pos] = gname

    for pos, gname in hdu_order.items():
        group = h[gname]
        pp.h2("Reading %s" % gname)

        # Form header dict from
        h_vals = {}
        for key, values in group.attrs.items():
            if key not in restricted_hdf_keywords:
                h_vals[key] = np.asscalar(values[0])
                #h_vals[key+"_COMMENT"] = values[1]

        #hk = group.attrs.keys()
        #hv = group.attrs.values()
        #h_vals = dict(zip(hk, hv))

        try:
            h_comment = group["COMMENT"]
        except KeyError:
            h_comment = None
        try:
            h_history = group["HISTORY"]
        except KeyError:
            h_history = None
        #header = IdiHeader(values=h_vals, comment=h_comment, history=h_history)
        #print header.vals.keys()

        pp.pp(group.keys())
        if "DATA" not in group:
            pp.h3("Adding Primary %s" % gname)
            hdulist.add_primary_hdu(gname, header=h_vals, history=h_history, comment=h_comment)

        elif group["DATA"].attrs["CLASS"] == "TABLE":
            pp.h3("Adding Table %s" % gname)
            #self.add_table(gname)
            data = IdiTableHdu(gname)

            for col_num in range(len(group["DATA"].dtype.fields)):
                col_name = group["DATA"].attrs["FIELD_%i_NAME" % col_num][0]
                col_units = group["DATA"].attrs["FIELD_%i_UNITS" % col_num][0]

                pp.debug("Reading col %s > %s" %(gname, col_name))
                dset = group["DATA"][col_name][:]

                #self[gname].data[dname] = dset[:]
                #self[gname].n_rows = dset.shape[0]

                idi_col = idi.IdiColumn(col_name, dset[:], unit=col_units)
                data.add_column(idi_col)
                col_num += 1

            hdulist.add_table_hdu(gname,
                           header=h_vals, data=data, history=h_history, comment=h_comment)

        elif group["DATA"].attrs["CLASS"] == "DATA_GROUP":
            pp.h3("Adding data group %s" % gname)
            data = IdiTableHdu(gname)

            # First, need to figure out column order
            col_order = {}
            #print group["DATA"].keys()
            for col_name in group["DATA"].keys():
                #print group["DATA"][col_name].attrs.items()
                pos = group["DATA"][col_name].attrs["COLUMN_ID"][0]
                col_order[pos] = col_name

            #print col_order

            for pos, col_name in col_order.items():
                pp.debug("Reading col %s > %s" %(gname, col_name))

                col_dset = group["DATA"][col_name]

                try:
                    col_units = col_dset.attrs["UNITS"][0]
                except:
                    col_units = None
                col_num   = col_dset.attrs["COLUMN_ID"][0]
                idi_col = idi.IdiColumn(col_name, col_dset[:], unit=col_units)
                data.add_column(idi_col)

            hdulist.add_table_hdu(gname,
                           header=h_vals, data=data, history=h_history, comment=h_comment)

        elif group["DATA"].attrs["CLASS"] == "IMAGE":
            pp.h3("Adding Image %s" % gname)
            hdulist.add_image_hdu(gname,
                           header=h_vals, data=group["DATA"][:], history=h_history, comment=h_comment)

        else:
            pp.warn("Cannot understand data class of %s" % gname)
        pp.debug(gname)
        pp.debug(hdulist[gname].header)
        #for hkey, hval in group["HEADER"].attrs.items():
        #    self[gname].header.vals[hkey] = hval

    h.close()

    return hdulist


def export_hdf(idi_hdu, outfile, **kwargs):
    """ Export to HDF file

    Keyword arguments
    -----------------
    compression=None, shuffle=False, chunks=None
    """

    try:
        assert isinstance(idi_hdu, IdiHdulist)
    except:
        raise RuntimeError("This function must be run on an IdiHdulist object")

    verbosity = 0
    if 'verbosity' in kwargs:
        verbosity = kwargs['verbosity']

    table_version1 = False

    h = h5py.File(outfile, mode='w')
    pp = PrintLog(verbosity=verbosity)

    #print outfile
    idi_hdu.hdf = h

    idi_hdu.hdf.attrs["CLASS"] = np.array(["HDFITS"])

    hdu_id = 0
    for gkey, gdata in idi_hdu.items():
        pp.h2("Creating %s" % gkey)
        hdu_id += 1

        # Create the new group
        gg = h.create_group(gkey)
        gg.attrs["CLASS"] = np.array(["HDU"])
        gg.attrs["POSITION"] = np.array([hdu_id])
        #hg = gg.create_group("HEADER")

        # Check if the data is a table
        if isinstance(idi_hdu[gkey], IdiTableHdu) and table_version1:
            try:
                            #self.pp.verbosity = 5
                #dg = gg.create_group("DATA")

                dd = idi_hdu[gkey]
                dd_data = dd._data

                if dd is not None:
                    dset = bs.create_dataset(gg, "DATA", dd_data, **kwargs)
                    dset.attrs["CLASS"] = np.array(["TABLE"])

                    col_num = 0
                    for col_name in dd.colnames:

                        column = dd[col_name]
                        col_dtype = column.dtype
                        col_units = column.unit.to_string()

                        if col_dtype.type is np.string_:
                            dset.attrs["FIELD_%i_FILL" % col_num] = np.array([''])
                        else:
                            dset.attrs["FIELD_%i_FILL" % col_num] = np.array([0])
                        dset.attrs["FIELD_%i_NAME" % col_num] = np.array([col_name])

                        dset.attrs["FIELD_%i_UNITS" % col_num] = np.array([str(col_units)])
                        col_num += 1

                    dset.attrs["NROWS"]   = np.array([dd.columns[0].shape[0]])
                    dset.attrs["VERSION"] = np.array([2.6])     #TODO: Move this version no
                    dset.attrs["TITLE"]   = np.array([gkey])

            except:
                pp.err("%s" % gkey)
                raise

        if isinstance(idi_hdu[gkey], IdiTableHdu) and not table_version1:
            try:
            # TODO: Reinstate code for DATA_STORE class (column store instead of HDF5 table)
                col_num = 0
                tbl_group = gg.create_group("DATA")
                tbl_group.attrs["CLASS"] = np.array(["DATA_GROUP"])

                for dkey, dval in idi_hdu[gkey].columns.items():
                    data = dval.data
                    #print "Adding col %s > %s" % (gkey, dkey)
                    pp.debug("Adding col %s > %s" % (gkey, dkey))

                    dset = bs.create_dataset(tbl_group, dkey, data, **kwargs)


                    dset.attrs["CLASS"] = np.array(["COLUMN"])
                    dset.attrs["COLUMN_ID"] = np.array([col_num])
                    if dval.unit:
                        dset.attrs["UNITS"] = np.array([str(dval.unit)])
                    col_num += 1
            except:
                pp.err("%s > %s" % (gkey, dkey))
                raise


        elif isinstance(idi_hdu[gkey], IdiImageHdu):
            pp.debug("Adding %s > DATA" % gkey)
            dset = bs.create_dataset(gg, "DATA", idi_hdu[gkey].data, **kwargs)

            # Add image-specific attributes
            dset.attrs["CLASS"] = np.array(["IMAGE"])
            dset.attrs["IMAGE_VERSION"] = np.array(["1.2"])
            if idi_hdu[gkey].data.ndim == 2:
                dset.attrs["IMAGE_SUBCLASS"] = np.array(["IMAGE_GRAYSCALE"])
                dset.attrs["IMAGE_MINMAXRANGE"] = np.array([np.min(idi_hdu[gkey].data), np.max(idi_hdu[gkey].data)])

        elif isinstance(idi_hdu[gkey], IdiPrimaryHdu):
            pass

        # Add header values
        #print self[gkey].header

        write_headers(gg, idi_hdu[gkey], verbosity=verbosity)
        #for hkey, hval in idi_hdu[gkey].header.items():
        #
        #    pp.debug("Adding header %s > %s" % (hkey, hval))
        #    gg.attrs[hkey] = np.array(hval)

        if idi_hdu[gkey].comment:
            gg.create_dataset("COMMENT", data=idi_hdu[gkey].comment)
        if idi_hdu[gkey].history:
            gg.create_dataset("HISTORY", data=idi_hdu[gkey].history)

    h.close()
