#!/usr/bin/env python3
#-*- coding: utf-8 -*-
# coding: utf-8


"""
Author: Arnaud Ferré
Mail: arnaud.ferre.pro@gmail.com
Description: If you have trained the module_train on a training set (terms associated with concept(s)), you can do here
    a prediction of normalization with a test set (new terms without pre-association with concept). NB : For now, you
    can only use a Sklearn object from the class LinearRegression.
    If you want to cite this work in your publication or to have more details:
    http://www.aclweb.org/anthology/W17-2312.
Dependency: Numpy lib (available with Anaconda)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at: http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""


#######################################################################################################
# Import modules & set up logging
#######################################################################################################
from io import open
from sklearn.externals import joblib
import numpy
import gensim
from sys import stderr, stdin
from optparse import OptionParser
from utils import word2term, onto
import json
import gzip
from sklearn.neighbors import NearestNeighbors
from scipy.spatial.distance import cosine
from sklearn.preprocessing import normalize


def metric_internal(metric):
    if metric == 'cosine':
        return 'euclidean'
    if metric == 'cosine-brute':
        return 'cosine'
    return metric

def metric_norm(metric, concept_vectors):
    if metric == 'cosine':
        return normalize(concept_vectors)
    return concept_vectors

def metric_sim(metric, d, vecTerm, vecConcept):
    if metric == 'cosine':
        return 1 - cosine(vecTerm, vecConcept)
    if metric == 'cosine-brute':
        return 1 - d
    return 1 / d



class VSONN(NearestNeighbors):
    def __init__(self, vso, metric):
        NearestNeighbors.__init__(self, algorithm='auto', metric=metric_internal(metric))
        self.original_metric = metric
        self.vso = vso
        self.concepts = tuple(vso.keys())
        self.concept_vectors = list(vso.values())
        self.fit(metric_norm(metric, self.concept_vectors))

    def nearest_concept(self, vecTerm):
        r = self.kneighbors([vecTerm], 1, return_distance=True)
        #stderr.write('r = %s\n' % str(r))
        d = r[0][0][0]
        idx = r[1][0][0]
        return self.concepts[idx], metric_sim(self.original_metric, d, vecTerm, self.concept_vectors[idx])




def predictor(vst_onlyTokens, dl_terms, vso, transformationParam, metric, symbol='___'):
    """
    Description: From a calculated linear projection from the training module, applied it to predict a concept for each
        terms in parameters (dl_terms).
    :param vst_onlyTokens: An initial VST containing only tokens and associated vectors.
    :param dl_terms: A dictionnary with id of terms for key and raw form of terms in value.
    :param vso: A VSO (dict() -> {"id" : [vector], ...}
    :param transformationParam: LinearRegression object from Sklearn. Use the one calculated by the training module.
    :param symbol: Symbol delimiting the different token in a multi-words term.
    :return: A list of tuples containing : ("term form", "term id", "predicted concept id") and a list of unknown tokens
        containing in the terms from dl_terms.
    """
    lt_predictions = list()

    vstTerm, l_unknownToken = word2term.wordVST2TermVST(vst_onlyTokens, dl_terms)

    result = dict()

    vsoTerms = dict()
    vsoNN = VSONN(vso, metric)
    for id_term in dl_terms.keys():
        termForm = word2term.getFormOfTerm(dl_terms[id_term], symbol)
        x = vstTerm[termForm].reshape(1, -1)
        vsoTerms[termForm] = transformationParam.predict(x)[0]
        result[termForm] = vsoNN.nearest_concept(vsoTerms[termForm])

    for id_term in dl_terms.keys():
        termForm = word2term.getFormOfTerm(dl_terms[id_term], symbol)
        cat, sim = result[termForm]
        prediction = (termForm, id_term, cat, sim)
        lt_predictions.append(prediction)

    return lt_predictions, l_unknownToken


def loadJSON(filename):
    if filename.endswith('.gz'):
        f = gzip.open(filename)
    else:
        f = open(filename, encoding='utf-8')
    result = json.load(f)
    f.close()
    return result;


class Predictor(OptionParser):
    def __init__(self):
        OptionParser.__init__(self, usage='usage: %prog [options]')
        self.add_option('--word-vectors', action='store', type='string', dest='word_vectors', help='path to word vectors file as produced by word2vec')
        self.add_option('--word-vectors-bin', action='store', type='string', dest='word_vectors_bin', help='path to word vectors binary file as produced by word2vec')
        self.add_option('--ontology', action='store', type='string', dest='ontology', help='path to ontology file in OBO format')
        self.add_option('--terms', action='append', type='string', dest='terms', help='path to terms file in JSON format (map: id -> array of tokens)')
        self.add_option('--factor', action='append', type='float', dest='factors', default=[], help='parent concept weight factor (default: 1.0)')
        self.add_option('--regression-matrix', action='append', type='string', dest='regression_matrix', help='path to the regression matrix file as produced by the training module')
        self.add_option('--output', action='append', type='string', dest='output', help='file where to write predictions')

        self.add_option('--metric', action='store', type='string', dest='metric', default='cosine', help='distance metric to use (default: %default)')

    def run(self):
        options, args = self.parse_args()
        if len(args) > 0:
            raise Exception('stray arguments: ' + ' '.join(args))
        if options.word_vectors is None and options.word_vectors_bin is None:
            raise Exception('missing either --word-vectors or --word-vectors-bin')
        if options.word_vectors is not None and options.word_vectors_bin is not None:
            raise Exception('incompatible --word-vectors or --word-vectors-bin')        
        if options.ontology is None:
            raise Exception('missing --ontology')
        if not(options.terms):
            raise Exception('missing --terms')
        if not(options.regression_matrix):
            raise Exception('missing --regression-matrix')
        if not(options.output):
            raise Exception('missing --output')
        if len(options.terms) != len(options.regression_matrix):
            raise Exception('there must be the same number of --terms and --regression-matrix')
        if len(options.terms) != len(options.output):
            raise Exception('there must be the same number of --terms and --output')
        if len(options.factors) > len(options.terms):
            raise Exception('there must be at least as many --terms as --factor')
        if len(options.factors) < len(options.terms):
            n = len(options.terms) - len(options.factors)
            stderr.write('defaulting %d factors to 1.0\n' % n)
            stderr.flush()
            options.factors.extend([1.0]*n)
        if options.word_vectors is not None:
            stderr.write('loading word embeddings: %s\n' % options.word_vectors)
            stderr.flush()
            word_vectors = loadJSON(options.word_vectors)
        elif options.word_vectors_bin is not None:
            stderr.write('loading word embeddings: %s\n' % options.word_vectors_bin)
            stderr.flush()
            model = gensim.models.Word2Vec.load(options.word_vectors_bin)
            word_vectors = dict((k, list(numpy.float_(npf32) for npf32 in model.wv[k])) for k in model.wv.vocab.keys())
        stderr.write('loading ontology: %s\n' % options.ontology)
        stderr.flush()
        ontology = onto.loadOnto(options.ontology)
        for terms_i, regression_matrix_i, output_i, factor_i in zip(options.terms, options.regression_matrix, options.output, options.factors):
            vso = onto.ontoToVec(ontology, factor_i)
            stderr.write('loading terms: %s\n' % terms_i)
            stderr.flush()
            terms = loadJSON(terms_i)
            stderr.write('loading regression matrix: %s\n' % regression_matrix_i)
            stderr.flush()
            regression_matrix = joblib.load(regression_matrix_i)
            stderr.write('predicting\n')
            stderr.flush()
            prediction, _ = predictor(word_vectors, terms, vso, regression_matrix, options.metric)
            stderr.write('writing predictions: %s\n' % output_i)
            stderr.flush()
            f = open(output_i, 'w')
            for _, term_id, concept_id, similarity in prediction:
                f.write('%s\t%s\t%f\n' % (term_id, concept_id, similarity))
            f.close()

if __name__ == '__main__':
    Predictor().run()
