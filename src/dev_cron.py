# This will maintain a 100 dqm file database at /nfs-6/${USER}/AutoDQM
import os
import sys
import json
import time
import ROOT
import getpass

import index
import search

def get_new(args, fmap):
        short = False
        datasets = search.list_of_datasets(args["cron"], short)

        to_write = []
        newest = fmap["newest"]

        for ds in datasets:
            dsname = ds["dataset"]
            files = search.get_dataset_files(dsname)
            file_dict = search.filelist_to_dict(files, short, num=10)

            for f in file_dict:
                if int(f["last_modified"]) > fmap["newest"]:
                    if (int(f["last_modified"]) > newest): newest = int(f["last_modified"])

                    name_split = f["name"].split("/000/")[1].split("/00000/")[0].split("/")
                    if len(name_split) > 1:
                        name = int(name_split[0] + name_split[1])
                    else:
                        name = int(name_split[0] + "000")

                    if name not in to_write:
                        to_write.append(name)

        to_write.sort(key=int)

        new_database = {"newest":newest, "timestamp":time.time(), "files":{}}
        for name in to_write:
            new_database["files"][name] = dsname

        if new_database["files"]:
            return new_database
        else: return None 

def handle_main(args):
    try:
        # with open("/nfs-6/userdata/{0}/AutoDQM/fmap.json".format(getpass.getuser()), "r") as fhin:
        #     fmap = json.load(fhin)
        with open("{0}/test.json".format(os.getcwd()), "r") as fhin:
            fmap = json.load(fhin)
    except ValueError:
        # fmap = {"newest": 1507364400}
        fmap = {"newest": 1508001500}

    f_dict = get_new(args, fmap)
    print(f_dict)
    if not f_dict["files"]: return

    # with open("/nfs-6/userdata/{0}/AutoDQM/fmap.json".format(getpass.getuser()), "w") as fout:
    #     json.dump(f_dict, fout, sort_keys=True, indent=4, separators=(',',':'))
    # with open("{0}/src/new_files.json".format(os.getcwd()), "w") as fout:
    #     json.dump(f_dict, fout, sort_keys=True, indent=4, separators=(',',':'))

    # dbase_dir = "/nfs-6/userdata/{0}/AutoDQM".format(getpass.getuser())
    # temp_dir = "/nfs-6/userdata/{0}/AutoDQM/temp".format(getpass.getuser())
    dbase_dir = "{0}/TEST".format(os.getcwd())
    temp_dir = "{0}/temp".format(os.getcwd())

    for run in f_dict["files"]:

        # Download and compile .root files, save to temp dir
        index.get_files(f_dict["files"][run], temp_dir, run)
        compiled_h = index.compile_hists(temp_dir)

        # Pack histograms into root file
        new_f = ROOT.TFile("{0}/{1}.root".format(dbase_dir, run))
        for hname in compiled_h:
            compiled_h[hname].Write()
        new_f.Close()

        # Clear temp dir
        os.system("rm {0}/*".format(temp_dir))

if __name__=='__main__':

    args = json.loads(sys.argv[1])

    handle_main(args)

