#!/usr/bin/env python
# coding: utf-8

import numpy as np
import pandas as pd
from scipy.stats import chisquare

from evidently.analyzers.base_analyzer import Analyzer
from .stattests.z_stattest import proportions_diff_z_stat_ind, proportions_diff_z_test
from .utils import process_columns
from .. import ColumnMapping
from evidently.analyzers.stattests import z_stat_test, chi_stat_test


# TODO: document somewhere, that all analyzers are mutators, i.e. they will change
#   the dataframe, like here: replace infs and nans. That means if far down the pipeline
#   somebody want to compute number of nans, the results will be 0.
#   Consider return copies of dataframes, even though it will drain memory for large datasets
from ..options import DataDriftOptions


def _remove_nans_and_infinities(dataframe):
    dataframe.replace([np.inf, -np.inf], np.nan, inplace=True)
    dataframe.dropna(axis=0, how='any', inplace=True)
    return dataframe


class CatTargetDriftAnalyzer(Analyzer):
    """Categorical target drift analyzer.

    Analyze categorical `target` and `prediction` distributions and provide calculations to the following questions:
    Does the model target behave similarly to the past period? Do my model predictions still look the same?

    For reference see https://evidentlyai.com/blog/evidently-014-target-and-prediction-drift
    """

    def calculate(self, reference_data: pd.DataFrame, current_data: pd.DataFrame,
                  column_mapping: ColumnMapping, options: DataDriftOptions = None) -> dict:
        """Calculate the target and prediction drifts.

        With default options, uses a chi² test when number of labels is greater than 2.
        Otherwise uses a z-test.

        Notes:
            Be aware that any nan or infinity values will be dropped from the dataframes in place.
            
            You can also provide a custom function that computes a statistic by setting
            options.cat_target_stattest_func value with the desired function.
            Such a function takes two arguments:

                def(reference_data: pd.Series, current_data: pd.Series):
                   ...

            and returns arbitrary number (like a p_value from the other tests ;-))
        Args:
            reference_data: usually the data which you used in training.
            current_data: new, unseen data to which we compare the reference data.
            column_mapping: a `ColumnMapping` object that contains references to the name of target and prediction
                columns
            options: a configuration for the calculation.
        Returns:
            A dictionary that contains some meta information as well as `metrics` for either target or prediction
            columns or both. The `*_drift` column in `metrics` contains a computed p_value from tests.
        """
        options = options or DataDriftOptions()
        columns = process_columns(reference_data, column_mapping)
        result = columns.as_dict()
        target_column = columns.utility_columns.target
        prediction_column = columns.utility_columns.prediction

        # TODO: consider replacing only values in target and prediction column, see comment above
        #   _remove_nans_and_infinities
        reference_data = _remove_nans_and_infinities(reference_data)
        current_data = _remove_nans_and_infinities(current_data)

        result['metrics'] = {}

        stattest_func = options.cat_target_stattest_func
        # target drift
        if target_column is not None:
            labels = set(reference_data[target_column]) | set(current_data[target_column])
            if not stattest_func:
                stattest_func = chi_stat_test if len(labels) > 2 else z_stat_test
            p_value = stattest_func(reference_data[target_column], current_data[target_column])
            result['metrics']["target_name"] = target_column
            result['metrics']["target_type"] = 'cat'
            result['metrics']["target_drift"] = p_value

        # prediction drift
        if prediction_column is not None:
            labels = set(reference_data[prediction_column]) | set(current_data[prediction_column])
            if not stattest_func:
                stattest_func = chi_stat_test if len(labels) > 2 else z_stat_test
            p_value = stattest_func(reference_data[prediction_column], current_data[prediction_column])
            result['metrics']["prediction_name"] = prediction_column
            result['metrics']["prediction_type"] = 'cat'
            result['metrics']["prediction_drift"] = p_value

        return result
