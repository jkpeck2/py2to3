# SPSS syntax Python 2 to Python 3 converter
# Requires Python 3.8+

# History
# 06-14-2020  Original version
# 01-15-2020  Improve error handling and reporting.  Work around api problem.

import glob, os, tempfile, re, shutil
from lib2to3.main import main as converter
# Need versions for V27
from extension import Template, Syntax, processcmd
import spss, spssaux
import logging


beginprogpat = r"begin +program *\.|begin +program +python *\."
endprogpat = r"end *program *\."

# debugging
    # makes debug apply only to the current thread
try:
    import wingdbstub
    import threading
    wingdbstub.Ensure()
    wingdbstub.debugger.SetDebugThreads({threading.get_ident(): 1})
except:
    pass

def fq(s):
    """return s with backquotes converted to /"""
    # This is needed to get around bug in the spss.PostOutput function
    return re.sub(r"\\", r"/", s)

###converter("lib2to3.fixes", args=[r"--output-dir=c:\converted",  "--nobackups", "--no-diffs", "--fix=all", "--fix=set_literal", "--fix=idioms", "--write", r"c:\temp\cases.py"])

def convert(filespec, outputloc, recursive=False, copyall=False, overwrite=False):
    """Convert SPSS syntax files or Python files from Python 2 to Python 3
    
    filespec is a file name or a wildcard specification.
    path separator must be written with /, not \ ??
    outputloc is the location where converted files are written.
    copyall specifies whether to copy unchanged files or not
    overwrite specifies whether to overwrite existing files or not
    The directory and any intermediate directories will be created if necessary.
    
    The recursive parameter is not yet supported.
    """
        
    tempdir = tempfile.TemporaryDirectory()
    temp1 = tempdir.name
    
    # support file handles
    fh = spssaux.FileHandles()
    outputloc = fh.resolve(outputloc)
    filespec = fh.resolve(filespec)
    
    ###os.makedirs(outputloc, exist_ok=True)  # raises exception if not possible
    # the lib2to3 conversion code and the SPSS print output functions interfere
    # with each other, so we divert the logging information to a file
    convlog  = outputloc + os.sep + "conversionMessages.txt"
    logging.basicConfig(filename=convlog, filemode="w", level=logging.INFO)
    
    filespec = os.path.abspath(filespec)
    #if recursive:
        #makeoutputlocs(filespec, outputloc)
    
    # py  success failure skipped
    # sps success failure skipped
    counts = [0, 0, 0, 0, 0, 0]
    for f in glob.glob(filespec, recursive=recursive):
        ext = os.path.splitext(f)[1].lower()
        if not ext in [".py", ".sps"]:
            continue
        thefile = os.path.basename(f)
        foutputloc = getoutputloc(f, outputloc)
        # ensure that file will not be overwritten or allow
        if not overwrite:
            try:
                if os.path.exists(foutputloc + os.path.sep + thefile):
                    print("*** %s already exists in output location.  Skipping conversion" % fq(thefile))
                    if ext == ".py":
                        counts[2] += 1
                    else:
                        counts[5] += 1
                    continue
            except:
                pass
        # convert file according to type, accumulating statistics
        if  ext == ".sps":
            if cvtsyntax(f, temp1, foutputloc, copyall):
                counts[3] += 1
            else:
                counts[4] += 1
        else:
            if cvtpy(f, foutputloc, copyall):
                counts[0] += 1
            else:
                counts[1] += 1
             
    print("\nAdditional conversion information (usually of limited usefulness) written to file: {0}".format(convlog))   
    pt = spss.StartProcedure("Convert Python 2")
    spss.AddProcedureFootnotes("Successful conversions should be checked for correctness")
    spss.AddProcedureFootnotes("Existing files overwrite option: {0}".format(overwrite))
    spss.AddProcedureFootnotes("Copy unchanged files option: {0}".format(copyall))
    pt = spss.BasePivotTable("File Conversions: {0}".format(filespec), "PythonConversionStats")
    pt.SimplePivotTable(rowlabels=['py', 'sps'],
        collabels=['Success', 'Failure', "Skipped"],
        cells=counts)
    spss.EndProcedure()
    logging.shutdown()


def cvtsyntax(f, temp1, outputloc, copyall):
    """ convert Python 2 code in syntax file to Python 3
    f is the file to convert
    If the file has no Python 2 blocks, it will not appear in the outputloc unless copyall.
    temp1 is a temporary directory used for BEGIN PROGRAM blocks
    outputloc is the location for the converted file
    """
    
    with open(f, "r") as inputf:
        hasPython2 = 0
        workingpath = temp1 + os.path.sep + os.path.basename(f)  # holds sps file copy
        with open(workingpath, "w") as working:
            for line in inputf:
                progstart = re.match(beginprogpat, line, flags=re.IGNORECASE)
                if not progstart:
                    working.write(line)
                else:
                    # extract  and replace a Python 2 block
                    working.write("BEGIN PROGRAM PYTHON3.\n")
                    hasPython2 += 1
                    t = tempfile.NamedTemporaryFile(dir=temp1, mode="w", suffix=".py", delete=False)   # create and open
                    with t as fragment:
                        try:
                            for line2 in inputf:
                                if re.match(endprogpat, line2, flags=re.IGNORECASE):
                                    break
                                else:
                                    fragment.write(line2)
                        except EOFError:
                            print("*** Missing END PROGRAM statement in file: %s.  Conversion skipped." % fq(f))
                            return False
                    fragment.close()
                    args=[r"--output-dir=%s" % temp1,  
                    "--nobackups", "--no-diffs", "--fix=all", "--fix=set_literal", "--fix=idioms", "--write", 
                    "--write-unchanged-files", t.name]
                    try:
                        res = converter("lib2to3.fixes", args=args)
                        ###args=[r"--output-dir=%s" % temp1,  
                        ###"--nobackups", "--no-diffs", "--fix=all", "--fix=set_literal", "--fix=idioms", "--write", 
                        ###t.name])
                    except:
                        print("*** Conversion failed.  File: %s" % fq(f))
                        return False
                    if res > 0:
                        print("*** Python block cannot be converted.  Conversion skipped.  File %s" % fq(f))
                        return False
                    with open(t.name) as p3code:
                        for line3 in p3code:
                            working.write(line3)
                        working.write(line2)    # END PROGRAM.
    if hasPython2 or copyall> 0:
        outfile = outputloc + os.path.sep + os.path.basename(f)
        shutil.copy(workingpath, outfile)
        print("file %s: converted %s blocks and saved as %s" % (fq(f), hasPython2, fq(outfile)))
        return True
    else:
        os.remove(workingpath)
        print("*** file: %s has no Python 2 blocks.  Not copied to output but counted as success." % fq(f))
        return True

def cvtpy(f, outputloc, copyall):
    """Convert Python 2 file to Python 3"""

    # --write specifies writing back modified files
    # --write-unchanged-files
    
    args=[r"--output-dir=%s" % outputloc,  
    "--nobackups", "--no-diffs", "--fix=all", "--fix=set_literal", "--fix=idioms", "--write", f]
    if copyall:
        args.append("--write-unchanged-files")
    try:
        res = converter("lib2to3.fixes", args=args)
    
        ###args=[r"--output-dir=%s" % outputloc,  
        ###"--nobackups", "--no-diffs", "--fix=all", "--fix=set_literal", "--fix=idioms", "--write", 
        ###f])
    except:
        print("*** Conversion failed.  File: %s" % fq(f))
        return False
    if res > 0:
        print("*** Conversion failed.  File %s" % fq(f))
        return False
    return True
    
def makeoutputlocs(filespec, outputloc):
    """create output locations implied by filespec with PYTHON3
    
    filespec is the input specification as absolute path
    outputloc is the location for output files"""
    
    subs = set([os.path.dirname(f) for f in glob.iglob(filespec, recursive=True)])
    fsdirsafe = re.escape(os.path.dirname(filespec))
    dirs = [re.sub(fsdirsafe, outputloc, item) for item in subs]
    for dir in dirs:
        os.makedirs(dir, exist_ok=True)
        
def getoutputloc(f, outloc):
    """Determine target location for file and create if needed.  Return target loc
    
    f is the filespec including path and filename
    outloc is the root of the target locations"""
    
    # The target location is outloc\fpath, where fpath is all but the first segment of the f directory
    
    if not outloc.endswith(('/', '\\')):
        outloc += os.sep
    dir = os.path.abspath(os.path.dirname(f))
    fhead = os.path.splitdrive(dir)[1]  # driveless spec
    parts = "/".join([item for item in re.split(r"[\\/]", fhead) if item != ""][1:]) # strip first segment of path
    targetloc = outloc + parts
    if (targetloc == dir):
        raise ValueError("Target location must be different from input location: {0}".format(targetloc))
    os.makedirs(targetloc, exist_ok=True)
    return targetloc

def Run(args):
    """Execute the STATS PYTHON continue extension command"""

    ###args = args[args.keys()[0]]
    args =args['STATS CONVERT PYTHON']

    oobj = Syntax([
        Template("FILES", ktype="literal", var="filespec", islist=False),
        Template("OUTPUTLOC", ktype="literal", var="outputloc", islist=False),
        Template("INCLUDESUBS",  ktype="bool", var="recursive"),
        Template("COPYALL", ktype="bool", var="copyall"),
        Template("OVERWRITE", ktype="bool", var="overwrite"),
        Template("HELP", subc="", ktype="bool")])
    
    #enable localization
    global _
    try:
        _("---")
    except:
        def _(msg):
            return msg
    # A HELP subcommand overrides all else
    if "HELP" in args:
        ###print helptext
        helper()
    else:
        processcmd(oobj, args, convert)
         
def helper():
    """open html help in default browser window
    
    The location is computed from the current module name"""
    
    import webbrowser, os.path
    
    path = os.path.splitext(__file__)[0]
    helpspec = "file://" + path + os.path.sep + \
         "markdown.html"
    
    # webbrowser.open seems not to work well
    browser = webbrowser.get()
    if not browser.open_new(helpspec):
        print("Help file not found:" + helpspec)
try:    #override
    from extension import helper
except:
    pass    


##if __name__ == "__main__":
    ##convert("c:/temp/toconvert.sps", "c:/temp/converted")
    
##if __name__ == "__main__":
    ##convert("c:/temp/toconvert[0-9].sps", "c:/temp/converted")    
    
##if __name__ == "__main__":
        ##convert("c:/temp/**/toconvert*.sps", "c:/temp/converted", recursive=True)    
    
#if __name__ == "__main__":
    #convert(r"c:\spss26\python\lib\site-packages\spssdata\spssdata.py", "c:/temp/converted")    
