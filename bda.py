#!/usr/local/env python3

__author__ = 'duceppemo, OldAdam70'
__version__ = '0.1.1'


import os
from nested_dict import nested_dict
from Bio import SeqIO
import os.path


class BDA(object):

    def __init__(self, args):
        import multiprocessing

        self.args = args
        self.input = args.input
        self.output = args.output

        # Check input file
        self.check_input_file(self.input)

        # Check output file
        self.check_output_file(self.output)

        # Number of cpu
        self.cpus = int(multiprocessing.cpu_count())

        # Empty ata structures
        self.blast_dict = nested_dict()
        self.contigs_dict = dict()

        # List of allowed file extensions
        self.allowed_ext = ['.fas', '.fasta', '.fa']

        # run the script
        self.run()

    def run(self):
        self.check_dependencies()
        self.check_input_file(self.input)
        self.parse_fasta(self.input)
        blast_handle = self.run_blastn('nr', self.input)
        self.parse_blast_output(blast_handle)

    def check_input_file(self, input_file):
        # Check if input file exists
        if not os.path.exists(input_file):
            raise Exception('Input file "{}" does not exist'.format(input_file))

        # Check if input file is a file
        if not os.path.isfile(input_file):
            raise Exception('Provided input "{}" is not a file'.format(input_file))

        # Check if input is a fasta file
        self.is_fasta(input_file)

    def check_output_file(self, output_file):
        # Check if output file was provided
        if self.output:
            # Check if output path exists, if not create it
            out_folder = os.path.dirname(output_file)
            if not os.path.exists(out_folder):
                os.makedirs(out_folder)
        else:
            # Output file is equal to input file with "_bda" append
            input_path = os.path.dirname(self.input)
            filename, input_ext = os.path.splitext(os.path.basename(self.input))
            self.output = input_path + '/' + filename + '_dba' + input_ext

    def is_fasta(self, fasta):
        with open(fasta) as f:
            first_line = f.readline()
        if first_line[:1] != '>':
            raise Exception("Input file {} is not valid fasta file")

    def parse_fasta(self, f):
        """
        Parse input fasta file using SeqIO from Biopython
        :param f: Assembly file in fasta format
        :return: Populated dictionary
        """

        self.contigs_dict = SeqIO.to_dict(SeqIO.parse(f, format='fasta'))

    def run_blastn(self, ref_db, query):
        """
        Perform blastn using biopython
        :param ref_db: A fasta file for which "makeblastdb' was already run
        :param query: Protein fasta file
        :return: blast handle
        """

        from Bio.Blast.Applications import NcbiblastpCommandline
        from io import StringIO

        print("Running blastp...")

        ref_db = '/media/30tb_raid10/db/nr/nr'
        blastx = NcbiblastpCommandline(db=ref_db, query=query, evalue='1e-10',
                                       outfmt=5, max_target_seqs=20,
                                       num_threads=self.cpus)
        (stdout, stderr) = blastx()

        if stderr:
            raise Exception('There was a problem with the blast:\n{}'.format(stderr))

        # Search stdout for matches - if the term Hsp appears (the .find function will NOT
        # return -1), a match has been found, and stdout is written to file
        if stdout.find('Hsp') != -1:
            blast_handle = StringIO(stdout)  # Convert string to IO object
        else:
            raise Exception("No blast results found.")

        return blast_handle

    def parse_blast_output(self, blast_handle):
        """
        test
        :param blast_handle: An xml Blast output file handle from io.StringIO
        :return:
        """
        from Bio import SearchIO

        # Create the list of words to filter out uninformative hits
        filter_strings = ['putative', 'protein like', 'protein related', 'contains similarity to',
                          'predicted', 'hypothetical protein', 'unnamed protein product',
                          'unknown', 'expressed protein', 'uncharacterized', 'probable',
                          'possible', 'potential']

        records_dict = SearchIO.to_dict(SearchIO.parse(blast_handle, 'blast-xml'))

        # Open output file handle in write mode
        with open(self.output, 'w') as f:
            for seq_id, qresult in records_dict.items():
                hit_descriptions = []
                e_values = []
                bit_scores = []
                proper_desc = 'hypothetical protein'

                for hit in qresult.hits:
                    hit_desc = hit.description

                    # Filter out uninformative hits here, create a list containing the remaining hits
                    # If there are hits left after the filtering, find the MIH
                    # If no hits are left after filtering, just return "hypothetical protein"
                    if not any([x in str(hit_desc).lower() for x in filter_strings]):
                        hit_descriptions.append(hit_desc)
                        e_values.append(hit.hsps[0].evalue)
                        bit_scores.append(hit.hsps[0].bitscore)

                if len(hit_descriptions) > 0:
                    proper_desc = self.identify_mih(hit_descriptions, bit_scores)

                    # Update description according to "find_best_description"
                    self.contigs_dict[seq_id].description = proper_desc

                    # Write to output file only the ones with new description
                    f.write('>{} {}\n{}\n'.format(seq_id, proper_desc, self.contigs_dict[seq_id].seq))

        # Close file StringIO handle
        blast_handle.close()

    def identify_mih(self, hits_list, bit_scores):
        """
        Identify most informative hit (mih)
        :param hits_list: a list containing the descriptors of hits for the current qresult
        :param bit_scores: a list of bit scores associated with the hits from the qresult
        :return: the most informative hit (MIH) descriptor
        """
        from nltk.corpus import stopwords
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.cluster import KMeans
        import numpy as np

        # Get the informative part of the hit description first by removing stopwords (common words)
        filtered_list = []
        for hit in hits_list:
            words_list = hit.lower().split()
            filtered_words = [word for word in words_list if word not in stopwords.words('english')]
            descriptor = " ".join(filtered_words).split("os=", 1)[0]
            filtered_list.append(descriptor)

        # Convert the description into a vector which can be used for clustering
        vectorizer = CountVectorizer()
        vectorized_hits = vectorizer.fit_transform(filtered_list)
        vector_array = np.array(vectorized_hits.toarray())

        # Create cluster centers, then test descriptions for which cluster they fall into
        if len(hits_list) < 8:
            kmeans = KMeans(n_clusters=len(hits_list), n_init=100).fit(vector_array)
        else:
            kmeans = KMeans(n_init=100).fit(vector_array)

        cluster_associations = kmeans.predict(vector_array)
        # Associate the bit scores with the cluster predictions
        cluster_aggregates = [(cluster, score) for cluster, score in zip(cluster_associations, bit_scores)]
        cluster_scores = [0] * 8

        # Determine which clustering contains the highest score
        # as a combination of number of bit scores and their values
        for cluster, score in cluster_aggregates:
            cluster_scores[cluster] += score

        # Find out what descriptions the highest scored cluster is associated with, and return the description
        mih_index = list(cluster_associations).index(cluster_scores.index(max(cluster_scores)))

        return hits_list[mih_index]

    def check_dependencies(self):
        pass


if __name__ == '__main__':

    from argparse import ArgumentParser

    parser = ArgumentParser(description='Reorder assembly to have the dnaA gene first')
    parser.add_argument('-i', '--input', metavar='input.fasta',
                        required=True,
                        help='Input fasta file to blast')
    parser.add_argument('-o', '--output', metavar='output_bda.fasta',
                        required=False,
                        help='Annotated fasta file with useful descriptions'
                             'Input file name appended with "_bda" will by used if no output file specified')

    # Get the arguments into an object
    arguments = parser.parse_args()

    BDA(arguments)
