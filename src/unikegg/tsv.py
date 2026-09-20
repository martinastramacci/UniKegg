"""One CSV/TSV dialect for upstream readers and lossless processed output."""

import csv

# MEDIUMTEXT is at most 16 MiB in bytes. Column validation checks byte limits;
# the CSV parser must not impose its much smaller default character limit.
FIELD_LIMIT = 16 * 1024 * 1024


def reader(stream):
    csv.field_size_limit(FIELD_LIMIT)
    return csv.reader(stream, delimiter="\t", strict=True)


def dict_reader(stream):
    csv.field_size_limit(FIELD_LIMIT)
    return csv.DictReader(stream, delimiter="\t", strict=True)


def writer(stream):
    # With MySQL ENCLOSED BY, unquoted NULL is SQL NULL. Quote *every* value,
    # including literal NULL, and use doubled quotes rather than backslashes.
    return csv.writer(stream, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_ALL)
