#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import errno
import json
import os
import requests
from collections import namedtuple

TIMEOUT = 5

BASE_URL = 'https://cmsweb.cern.ch'
DQM_URL = 'https://cmsweb.cern.ch/dqm/offline/data/browse/ROOT/OfflineData/'
CA_URL = 'https://cafiles.cern.ch/cafiles/certificates/CERN%20Root%20Certification%20Authority%202.crt'

# The following are appended to the db dir
CACHE_DIR = 'cache/'
CA_PATH = 'CERN_Root_CA.crt'

StreamProg = namedtuple('StreamProg', ('cur', 'total', 'path'))
DQMRow = namedtuple('DQMRow', ('name', 'full_name', 'url', 'size', 'date'))

def FuturesSession():
    """
    FuturesSession imported from within this function, and is called in the code
    """
    from requests_futures.sessions import FuturesSession
    return FuturesSession

class DQMSession(FuturesSession()):
    """
    Encapsulates an interface to DQM Offline.
    """

    def __init__(self, cert, db, cache=None, workers=16):
        super(DQMSession, self).__init__(max_workers=workers)

        self.db = db
        if cache:
            self.cache = cache
        else:
            self.cache = os.path.join(self.db, CACHE_DIR)

        self.cert = cert
        self.verify = os.path.join(db, CA_PATH)
        if not os.path.exists(self.verify):
            _get_cern_ca(self.verify)

    def fetch_run(self, series, sample, run):
        """
	Fetch and cache a run data file.

        Returns the path to the downloaded file.
        """
        dl = self.stream_run(series, sample, run)

        # Get the path from the first yield
        path = next(dl).path

        # Finish the download
        for _ in dl:
            pass
        return path

    def stream_run(self, series, sample, run, chunk_size=4096):
        """
	Stream and cache a run data file.

        Returns a generator that yields StreamProg tuples corresponding to the
        download progress.
        """
	run_path = self._run_path(series, sample, run)
        run_dir = os.path.dirname(run_path)

        if not os.path.exists(run_path):
            _try_makedirs(run_dir)

            runs = self.fetch_run_list(series, sample)
            run_info = next(r for r in runs if r.name == run)

            for prog in self._stream_file(
                    run_info.url, run_path, chunk_size=chunk_size):
                yield prog
        size = os.path.getsize(run_path)
        yield StreamProg(size, size, run_path)

    def fetch_series_list(self):
        """
	Return DQMRows corresponding to the series available on DQM Offline.
        """
	return _resolve(self._fetch_dqm_rows(DQM_URL)).data

    def fetch_sample_list(self, series):
        """
	Return DQMRows corresponding to the samples available under the given series.
        """
	series_rows = self.fetch_series_list()
        url = next((r.url for r in series_rows if r.name == series))
        return _resolve(self._fetch_dqm_rows(url)).data

    def fetch_run_list(self, series, sample):
        """
	Return DQMRows corresponding to the runs available under the given series and sample.
        """
	sample_rows = self.fetch_sample_list(series)
        sample_url = next((r.url for r in sample_rows if r.name == sample))

        # Get all run directories for this sample
        macrorun_rows = _resolve(self._fetch_dqm_rows(sample_url)).data

        # Determine which run directories are cached
        run_rows = []
        to_req = []
        for mr in macrorun_rows:
            rows = self._get_cache(mr)
            if rows:
                run_rows += rows
            else:
                to_req.append(mr)

        # Request uncached directories from the servers
        futures = [(mr, self._fetch_dqm_rows(mr.url)) for mr in to_req]
        for mr, fut in futures:
            rows = _resolve(fut).data
            run_rows += rows
            self._write_cache(mr, rows)

        return run_rows

    def _get_cache(self, parent_row):
        """sample_url = next((r.url for r in sample_rows if r.name == sample))

        # Get all run directories for this sample
        macrorun_rows = _resolve(self._fetch_dqm_rows(sample_url)).data

        # Determine which run directories are cached
        run_rows = []
        to_req = []

        for mr in macrorun_rows:
            rows = self._get_cache(mr)
            if rows:
                run_rows += rows
            else:
                to_req.append(mr)

        # Request uncached directories from the servers
        futures = [(mr, self._fetch_dqm_rows(mr.url)) for mr in to_req]
        for mr, fut in futures:
            rows = _resolve(fut).data
            run_rows += rows
            self._write_cache(mr, rows)

        return run_rows

    def _get_cache(self, parent_row):
        """
        Return the DQM page corresponding to parent_row as DQMRows if they are cached. Otherwise None.
        """
	cache_file = self._cache_path(parent_row)
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                dat = json.load(f)
                return [DQMRow(*r) for r in dat]
        else:
            return None

    def _write_cache(self, parent_row, dqm_rows):
        """
	Write a list of DQMRows to the cache under their parent_row.
        """
	cache_file = self._cache_path(parent_row)
        _try_makedirs(os.path.dirname(cache_file))
        with open(cache_file, 'w') as f:
            json.dump(dqm_rows, f)

    def _cache_path(self, parent_row):
        """
	Return the path to a cached DQM page specified by its parent DQMRow.
        """
	return os.path.join(self.cache, str(abs(hash(parent_row))))

    def _fetch_dqm_rows(self, url, timeout=TIMEOUT):
        """
	Return a future of DQMRows of a DQM page at url.

        Access the array of DQMRows at _resolve(self._fetch_dqm_rows(...)).data
        """

	# Callback to process dqm responses
        def cb(sess, resp):
            resp.data = _parse_dqm_page(resp.text)

        return self.get(url, timeout=timeout, background_callback=cb)

    def _stream_file(self, url, dest, chunk_size=4096):
        """
	Stream a file into a destination path.

        Returns a generator of StreamProg tuples to indicate download progress.
        """
	res = _resolve(self.get(url, stream=True))
        if not res:
            raise error("Failed to download file: {}".format(url))

        total = int(res.headers.get('content-length'))
        cur = 0
        try:
            with open(dest, 'wb') as f:
                yield StreamProg(cur, total, dest)
                for data in res.iter_content(chunk_size=chunk_size):
                    cur += len(data)
                    f.write(data)
                    yield StreamProg(cur, total, dest)
            if cur != total:
                raise error(
                    "Failed to stream file: Final size {} less than total {}"
                    .format(cur, total))
        except:
            # Remove the file if anything went wrong in the middle
            os.remove(dest)
            raise

    def _run_path(self, series, sample, run):
        """Return the path to the specified run data file in the cached db."""
        return "{}/{}.root".format(os.path.join(self.db, series, sample), run)
