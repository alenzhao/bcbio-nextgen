"""Annotate structural variant calls with associated genes.
"""
import os

from bcbio import utils
from bcbio.bam import ref
from bcbio.distributed.transaction import file_transaction
from bcbio.pipeline import datadict as dd
from bcbio.provenance import do
from bcbio.structural import regions
from bcbio.variation import bedutils

import pybedtools

def add_genes(in_file, data, max_distance=10000, work_dir=None):
    """Add gene annotations to a BED file from pre-prepared RNA-seq data.

    max_distance -- only keep annotations within this distance of event
    """
    gene_file = regions.get_sv_bed(data, "exons", out_dir=os.path.dirname(in_file))
    if gene_file and utils.file_exists(in_file):
        out_file = "%s-annotated.bed" % utils.splitext_plus(in_file)[0]
        if work_dir:
            out_file = os.path.join(work_dir, os.path.basename(out_file))
        if not utils.file_uptodate(out_file, in_file):
            fai_file = ref.fasta_idx(dd.get_ref_file(data))
            with file_transaction(data, out_file) as tx_out_file:
                add_genes_to_bed(in_file, gene_file, fai_file, tx_out_file, max_distance)
        return out_file
    else:
        return in_file

def add_genes_to_bed(in_file, gene_file, fai_file, out_file, max_distance=10000):
    """Re-usable subcomponent that annotates BED file genes from another BED
    """
    input_rec = iter(pybedtools.BedTool(in_file)).next()
    # keep everything after standard chrom/start/end, 1-based
    extra_fields = range(4, len(input_rec.fields) + 1)
    # keep the new gene annotation
    gene_index = len(input_rec.fields) + 4
    extra_fields.append(gene_index)
    columns = ",".join([str(x) for x in extra_fields])
    max_column = max(extra_fields) + 1
    ops = ",".join(["distinct"] * len(extra_fields))
    # swap over gene name to '.' if beyond maximum distance
    # cut removes the last distance column which can cause issues
    # with bedtools merge: 'ERROR: illegal character '.' found in integer conversion of string'
    distance_filter = (r"""awk -F$'\t' -v OFS='\t' '{if ($NF > %s) $%s = "."} {print}'""" %
                       (max_distance, gene_index))
    sort_cmd = bedutils.get_sort_cmd()
    cat_cmd = "zcat" if in_file.endswith(".gz") else "cat"
    cmd = ("{cat_cmd} {in_file} | grep -v ^track | grep -v ^browser | grep -v ^# | "
           "{sort_cmd} -k1,1 -k2,2n | "
            "bedtools closest -g <(cut -f1,2 {fai_file} | {sort_cmd} -k1,1 -k2,2n) "
            "-d -t all -a - -b <({sort_cmd} -k1,1 -k2,2n {gene_file}) | "
            "{distance_filter} | cut -f 1-{max_column} | "
            "bedtools merge -i - -c {columns} -o {ops} -delim ',' > {out_file}")
    do.run(cmd.format(**locals()), "Annotate BED file with gene info")
