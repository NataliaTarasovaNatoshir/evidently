import json
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import dataclasses
import pandas as pd
from pandas.api.types import is_numeric_dtype
from pandas.api.types import is_string_dtype

from evidently.calculations.data_quality import DataQualityGetPlotData
from evidently.calculations.data_quality import FeatureQualityStats
from evidently.calculations.data_quality import get_features_stats
from evidently.metrics.base_metric import InputData
from evidently.metrics.base_metric import Metric
from evidently.model.widget import AdditionalGraphInfo
from evidently.model.widget import BaseWidgetInfo
from evidently.renderers.base_renderer import MetricRenderer
from evidently.renderers.base_renderer import default_renderer
from evidently.utils.data_operations import process_columns
from evidently.utils.data_preprocessing import ColumnType, DataDefinition
from evidently.utils.types import Numeric
from evidently.utils.visualizations import plot_boxes
from evidently.utils.visualizations import plot_cat_cat_rel
from evidently.utils.visualizations import plot_cat_feature_in_time
from evidently.utils.visualizations import plot_distr
from evidently.utils.visualizations import plot_distr_with_log_button
from evidently.utils.visualizations import plot_num_feature_in_time
from evidently.utils.visualizations import plot_num_num_rel
from evidently.utils.visualizations import plot_time_feature_distr
from evidently.renderers import html_widgets

from evidently.features.text_length_feature import TextLength
from evidently.features.non_letter_character_percentage_feature import NonLetterCharacterPercentage
from evidently.features.OOV_words_percentage_feature import OOVWordsPercentage


@dataclasses.dataclass
class NumericCharacteristics:
    number_of_rows: int
    count: int
    mean: Optional[Numeric]
    std: Optional[Numeric]
    min: Optional[Numeric]
    p25: Optional[Numeric]
    p50: Optional[Numeric]
    p75: Optional[Numeric]
    max: Optional[Numeric]
    unique: Optional[int]
    unique_percentage: Optional[float]
    missing: Optional[int]
    missing_percentage: Optional[float]
    infinite_count: Optional[int]
    infinite_percentage: Optional[float]
    most_common: Optional[Union[int, float]]
    most_common_percentage: Optional[float]


@dataclasses.dataclass
class CategoricalCharacteristics:
    number_of_rows: int
    count: int
    unique: Optional[int]
    unique_percentage: Optional[float]
    most_common: Optional[object]
    most_common_percentage: Optional[float]
    missing: Optional[int]
    missing_percentage: Optional[float]
    new_in_current_values_count: Optional[int] = None
    unused_in_current_values_count: Optional[int] = None


@dataclasses.dataclass
class DatetimeCharacteristics:
    number_of_rows: int
    count: int
    unique: Optional[int]
    unique_percentage: Optional[float]
    most_common: Optional[object]
    most_common_percentage: Optional[float]
    missing: Optional[int]
    missing_percentage: Optional[float]
    first: Optional[str]
    last: Optional[str]


ColumnCharacteristics = Union[NumericCharacteristics, CategoricalCharacteristics, DatetimeCharacteristics]


@dataclasses.dataclass
class DataInTime:
    data_for_plots: Dict[str, pd.DataFrame]
    freq: str
    datetime_name: str


@dataclasses.dataclass
class DataByTarget:
    data_for_plots: Dict[str, Dict[str, Union[list, pd.DataFrame]]]
    target_name: str
    target_type: str


@dataclasses.dataclass
class DataQualityPlot:
    bins_for_hist: Dict[str, pd.DataFrame]
    data_in_time: Optional[DataInTime]
    data_by_target: Optional[DataByTarget]
    counts_of_values: Optional[Dict[str, pd.DataFrame]]


@dataclasses.dataclass
class ColumnSummaryOneCol:
    column_name: str
    column_type: str
    reference_characteristics: Optional[ColumnCharacteristics]
    current_characteristics: ColumnCharacteristics
    plot_data: DataQualityPlot


@dataclasses.dataclass
class ColumnSummary:
    column_name: str
    column_type: str
    reference_characteristics: Optional[ColumnCharacteristics]
    current_characteristics: Optional[ColumnCharacteristics]
    plot_data: Optional[DataQualityPlot]
    text_gen_col_summaries: Optional[List[ColumnSummaryOneCol]]
    freq_plot_data: Optional[Dict[str, pd.DataFrame]]
    show_words_frequencies: Optional[bool]


class ColumnSummaryMetric(Metric[ColumnSummary]):
    def __init__(self, column_name: str, show_words_frequencies=True):
        self.column_name = column_name
        self.show_words_frequencies=show_words_frequencies

    @staticmethod
    def acceptable_types() -> List[ColumnType]:
        return [ColumnType.Numerical, ColumnType.Categorical, ColumnType.Text]

    def calculate(self, data: InputData) -> ColumnSummary:
        columns = process_columns(data.current_data, data.column_mapping)

        if self.column_name not in data.current_data:
            raise ValueError(f"Column '{self.column_name}' not found in current dataset.")

        if data.reference_data is not None and self.column_name not in data.reference_data:
            raise ValueError(f"Column '{self.column_name}' not found in reference dataset.")

        column_type = None
        target_name = columns.utility_columns.target
        target_type = None
        data_by_target = None

        # define target type and prediction type. TODO move it to process_columns func
        if columns.utility_columns.target is not None:
            reg_condition = data.column_mapping.task == "regression" or (
                is_numeric_dtype(data.current_data[target_name])
                and columns.task != "classification"
                and data.current_data[target_name].nunique() > 5
            )
            if reg_condition:
                target_type = "num"
            else:
                target_type = "cat"
            if target_name == self.column_name:
                column_type = target_type

        if columns.utility_columns.prediction is not None:
            if (
                isinstance(columns.utility_columns.prediction, str)
                and columns.utility_columns.prediction == self.column_name
            ):
                if (
                    is_string_dtype(data.current_data[columns.utility_columns.prediction])
                    or (
                        is_numeric_dtype(data.current_data[columns.utility_columns.prediction])
                        and columns.task != "classification"
                        and data.current_data[columns.utility_columns.prediction].nunique() < 5
                    )
                    or (
                        is_numeric_dtype(data.current_data[columns.utility_columns.prediction])
                        and columns.task == "classification"
                        and (
                            data.current_data[columns.utility_columns.prediction].max() > 1
                            or data.current_data[columns.utility_columns.prediction].min() < 0
                        )
                    )
                ):
                    column_type = "cat"
                else:
                    column_type = "num"

            if (
                isinstance(columns.utility_columns.prediction, list)
                and self.column_name in columns.utility_columns.prediction
            ):
                column_type = "num"
        if self.column_name in columns.num_feature_names:
            column_type = "num"
        elif self.column_name in columns.cat_feature_names:
            column_type = "cat"
        elif self.column_name in columns.datetime_feature_names or (
            columns.utility_columns.date is not None and columns.utility_columns.date == self.column_name
        ):
            column_type = "datetime"
        elif self.column_name in columns.text_feature_names:
            column_type = 'text'
        if column_type is None:
            raise ValueError(f"column {self.column_name} not in num, cat or datetime features lists")

        if column_type == 'text':
            res_summaries = []
            # generate auto-generated columns
            for gen_feature in self.generated_text_features:
                curr_characteristics, ref_characteristics, reference_data = \
                    self._get_ref_cur_characteristics(data, column_type='num',
                                                      column_name=gen_feature.feature_name())
                plot_data = self._get_plot_data(data, reference_data, column_type='num', columns=columns,
                                                target_name=target_name, target_type=target_type,
                                                column_name=gen_feature.feature_name())

                res_summaries.append(ColumnSummaryOneCol(column_name=gen_feature.feature_name().name,
                                                         column_type='num',
                                                         reference_characteristics=ref_characteristics,
                                                         current_characteristics=curr_characteristics,
                                                         plot_data=plot_data))
            if self.show_words_frequencies:
                freq_plot_data = self._calc_top_words_frequencies(data, k=10)
            else: freq_plot_data = None

            return ColumnSummary(
                column_name=self.column_name,
                column_type=column_type,
                text_gen_col_summaries=res_summaries,
                reference_characteristics=None,
                current_characteristics=None,
                plot_data=None,
                freq_plot_data=freq_plot_data,
                show_words_frequencies=self.show_words_frequencies
            )

        curr_characteristics, ref_characteristics, reference_data = self._get_ref_cur_characteristics(data, column_type,
                                                                                                      self.column_name)

        plot_data = self._get_plot_data(data, reference_data, column_type, columns, target_name, target_type, self.column_name)

        return ColumnSummary(
            column_name=self.column_name,
            column_type=column_type,
            reference_characteristics=ref_characteristics,
            current_characteristics=curr_characteristics,
            plot_data=plot_data,
            text_gen_col_summaries=None,
            freq_plot_data=None,
            show_words_frequencies=False
        )

    def required_features(self, data_definition: DataDefinition):
        column_type = data_definition.get_column(self.column_name).column_type
        self.generated_text_features = []
        self.generated_text_features.append(TextLength(self.column_name))
        self.generated_text_features.append(NonLetterCharacterPercentage(self.column_name))
        self.generated_text_features.append(OOVWordsPercentage(self.column_name))
        if column_type == ColumnType.Text:
            return self.generated_text_features
        return []

    @staticmethod
    def map_data(stats: FeatureQualityStats) -> ColumnCharacteristics:
        if stats.feature_type == "num":
            if isinstance(stats.max, str) or isinstance(stats.min, str) or isinstance(stats.most_common_value, str):
                raise ValueError("max / min stats should be int or float type, but got str")
            return NumericCharacteristics(
                number_of_rows=stats.number_of_rows,
                count=stats.count,
                mean=stats.mean,
                std=stats.std,
                min=stats.min,
                max=stats.max,
                p25=stats.percentile_25,
                p50=stats.percentile_50,
                p75=stats.percentile_75,
                unique=stats.unique_count,
                unique_percentage=stats.unique_percentage,
                missing=stats.missing_count,
                missing_percentage=stats.missing_percentage,
                infinite_count=stats.infinite_count,
                infinite_percentage=stats.infinite_percentage,
                most_common=stats.most_common_value,
                most_common_percentage=stats.most_common_value_percentage,
            )
        if stats.feature_type == "cat":
            return CategoricalCharacteristics(
                number_of_rows=stats.number_of_rows,
                count=stats.count,
                unique=stats.unique_count,
                unique_percentage=stats.unique_percentage,
                most_common=stats.most_common_value,
                most_common_percentage=stats.most_common_value_percentage,
                missing=stats.missing_count,
                missing_percentage=stats.missing_percentage,
            )
        if stats.feature_type == "datetime":
            if not isinstance(stats.min, str) or not isinstance(stats.max, str):
                raise ValueError(f"min / max expected to be str for datetime, got {type(stats.min)}/{type(stats.max)}")
            return DatetimeCharacteristics(
                number_of_rows=stats.number_of_rows,
                count=stats.count,
                unique=stats.unique_count,
                unique_percentage=stats.unique_percentage,
                most_common=stats.most_common_value,
                most_common_percentage=stats.most_common_value_percentage,
                missing=stats.missing_count,
                missing_percentage=stats.missing_percentage,
                first=stats.min,
                last=stats.max,
            )
        raise ValueError(f"unknown feature type {stats.feature_type}")

    @staticmethod
    def col_summary_to_col_summary_one_col(col_summary: ColumnSummary) -> ColumnSummaryOneCol:
        return ColumnSummaryOneCol(
            column_name=col_summary.column_name,
            column_type=col_summary.column_type,
            reference_characteristics=col_summary.reference_characteristics,
            current_characteristics=col_summary.current_characteristics,
            plot_data=col_summary.plot_data,
        )

    def _get_ref_cur_characteristics(self, data, column_type, column_name):
        reference_data = None
        ref_characteristics = None
        if data.reference_data is not None:
            reference_data = data.reference_data
            ref_characteristics = self.map_data(get_features_stats(data.get_reference_column(column_name), column_type))
        curr_characteristics = self.map_data(get_features_stats(data.get_current_column(column_name), column_type))

        if data.reference_data is not None and column_type == "cat":
            current_values_set = set(data.get_current_column(column_name).unique())
            reference_values_set = set(data.get_reference_column(column_name).unique())
            unique_in_current = current_values_set - reference_values_set
            new_in_current_values_count: int = len(unique_in_current)
            unique_in_reference = reference_values_set - current_values_set
            unused_in_current_values_count: int = len(unique_in_reference)
            if any(pd.isnull(list(unique_in_current))) and any(pd.isnull(list(unique_in_reference))):
                new_in_current_values_count -= 1
                unused_in_current_values_count -= 1
            if not isinstance(curr_characteristics, CategoricalCharacteristics):
                raise ValueError(f"{self.column_name} should be categorical")
            curr_characteristics.new_in_current_values_count = new_in_current_values_count
            curr_characteristics.unused_in_current_values_count = unused_in_current_values_count

        return curr_characteristics, ref_characteristics, reference_data

    def _get_plot_data(self, data, reference_data, column_type, columns, target_name, target_type, column_name):
        # plot data
        gpd = DataQualityGetPlotData()
        bins_for_hist = gpd.calculate_main_plot(data, column_name, column_type)
        data_in_time = None
        if (
                columns.utility_columns.date is not None
                and columns.utility_columns.date != column_name
                and column_type != "datetime"
        ):
            data_in_time = gpd.calculate_data_in_time(
                data,
                column_name,
                column_type,
                columns.utility_columns.date,
            )
            data_in_time = DataInTime(
                data_for_plots={
                    "current": data_in_time["current"],
                    "reference": data_in_time["reference"],
                },
                freq=data_in_time["freq"],
                datetime_name=data_in_time["datetime_name"],
            )
        data_by_target = None
        if (
                target_name is not None
                and target_type is not None
                and columns.utility_columns.target != column_name
                and column_type != "datetime"
        ):
            data_for_plots = gpd.calculate_data_by_target(
                data,
                column_name,
                column_type,
                target_name,
                target_type,
            )
            data_by_target = DataByTarget(
                data_for_plots=data_for_plots,
                target_name=target_name,
                target_type=target_type,
            )
        counts_of_values = None
        if column_type in ["cat", "num"]:
            counts_of_values = {}
            current_counts = data.get_current_column(column_name).value_counts(dropna=False).reset_index()
            current_counts.columns = ["x", "count"]
            counts_of_values["current"] = current_counts.head(10)
            if reference_data is not None:
                reference_counts = data.get_reference_column(column_name).value_counts(dropna=False).reset_index()
                reference_counts.columns = ["x", "count"]
                counts_of_values["reference"] = reference_counts.head(10)

        plot_data = DataQualityPlot(
            bins_for_hist=bins_for_hist,
            data_in_time=data_in_time,
            data_by_target=data_by_target,
            counts_of_values=counts_of_values,
        )

        return plot_data

    def _calc_top_words_frequencies(self, data: InputData, k=10):
        from evidently.features.text_utils import get_frequencies
        result = {}
        freqs_cur = data.get_current_column(self.column_name).apply(lambda x: get_frequencies(x, lemmatize=True)).sum()
        total_freqs_cur = sum(freqs_cur.values())
        top_words = [word[0] for word in freqs_cur.most_common(k)]

        if data.reference_data is not None:
            freqs_ref = data.get_reference_column(self.column_name).apply(
                lambda x: get_frequencies(x, lemmatize=True)).sum()
            total_freqs_ref = sum(freqs_ref.values())
            top_ref_words = [word[0] for word in freqs_ref.most_common(k)]
            top_words = set(top_words)
            top_words.update(set(top_ref_words))
            top_words = list(top_words)
        result['current'] = pd.DataFrame({'x': top_words,
                                          'count': [freqs_cur[word] / total_freqs_cur for word in top_words]})
        result['current'].sort_values('count', ascending=False, inplace=True)
        if data.reference_data is not None:
            result['reference'] = pd.DataFrame({'x': top_words,
                                                'count': [freqs_ref[word] / total_freqs_ref for word in top_words]})
        return result


@default_renderer(wrap_type=ColumnSummaryMetric)
class ColumnSummaryMetricRenderer(MetricRenderer):
    def render_json(self, obj: ColumnSummaryMetric) -> dict:
        result = dataclasses.asdict(obj.get_result())
        if result["column_type"] == 'text':
            for i in range(len(result['text_gen_col_summaries'])):
                result['text_gen_col_summaries'][i].pop("plot_data", None)
            return result
        result.pop("plot_data", None)
        return result

    def render_html(self, obj: ColumnSummaryMetric) -> List[BaseWidgetInfo]:
        metric_result = obj.get_result()
        column_type = metric_result.column_type
        column_name = metric_result.column_name
        show_words_frequencies = metric_result.show_words_frequencies

        if column_type == 'text':
            widgets = []
            if show_words_frequencies:
                widgets = [self._get_word_freq_widget(bins_for_hist=metric_result.freq_plot_data)]
            for el in metric_result.text_gen_col_summaries:
                metric_result_col = el
                column_type_col = el.column_type
                column_name_col = el.column_name
                widgets.extend(self._get_widgets_for_one_col(metric_result_col, column_type_col, column_name_col))
            return widgets

        return self._get_widgets_for_one_col(metric_result, column_type, column_name)

    def _get_word_freq_widget(self, bins_for_hist):
        hist_curr = bins_for_hist["current"]
        hist_ref = None
        if "reference" in bins_for_hist.keys():
            hist_ref = bins_for_hist["reference"]
        fig = plot_distr(hist_curr=hist_curr, hist_ref=hist_ref, color_options=self.color_options)
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        w1 = html_widgets.plotly_figure(title="Most frequent words", figure=fig)
        return w1

    def _get_widgets_for_one_col(self, metric_result, column_type, column_name):
        # main plot
        bins_for_hist = metric_result.plot_data.bins_for_hist
        hist_curr = bins_for_hist["current"]
        hist_ref = None
        metrics_values_headers = [""]
        if "reference" in bins_for_hist.keys():
            hist_ref = bins_for_hist["reference"]
            metrics_values_headers = ["current", "reference"]

        if column_type == "cat":
            fig = plot_distr(hist_curr=hist_curr, hist_ref=hist_ref, color_options=self.color_options)
            fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            fig = json.loads(fig.to_json())
        if column_type == "num":
            ref_log = None
            if "reference_log" in bins_for_hist.keys():
                ref_log = bins_for_hist["reference_log"]
            fig = plot_distr_with_log_button(
                hist_curr, bins_for_hist["current_log"], hist_ref, ref_log, color_options=self.color_options
            )
        if column_type == "datetime":
            fig = plot_time_feature_distr(hist_curr, hist_ref, column_name, color_options=self.color_options)

        # additional plots
        additional_graphs = []
        parts = []
        if metric_result.plot_data.data_in_time is not None:
            if column_type == "num":
                feature_in_time_figure = plot_num_feature_in_time(
                    metric_result.plot_data.data_in_time.data_for_plots["current"],
                    metric_result.plot_data.data_in_time.data_for_plots["reference"],
                    column_name,
                    metric_result.plot_data.data_in_time.datetime_name,
                    metric_result.plot_data.data_in_time.freq,
                    color_options=self.color_options,
                )
            if column_type == "cat":
                feature_in_time_figure = plot_cat_feature_in_time(
                    metric_result.plot_data.data_in_time.data_for_plots["current"],
                    metric_result.plot_data.data_in_time.data_for_plots["reference"],
                    column_name,
                    metric_result.plot_data.data_in_time.datetime_name,
                    metric_result.plot_data.data_in_time.freq,
                    color_options=self.color_options,
                )
            additional_graphs.append(
                AdditionalGraphInfo(
                    column_name + "_in_time",
                    {
                        "data": feature_in_time_figure["data"],
                        "layout": feature_in_time_figure["layout"],
                    },
                )
            )
            parts.append({"title": column_name + " in time", "id": column_name + "_in_time"})

        if metric_result.plot_data.data_by_target is not None:
            ref_data_by_target = None
            if "reference" in metric_result.plot_data.data_by_target.data_for_plots.keys():
                ref_data_by_target = metric_result.plot_data.data_by_target.data_for_plots["reference"]
            target_type = metric_result.plot_data.data_by_target.target_type
            target_name = metric_result.plot_data.data_by_target.target_name
            if column_type == "num" and target_type == "cat":
                feature_by_target_figure = plot_boxes(
                    metric_result.plot_data.data_by_target.data_for_plots["current"],
                    ref_data_by_target,
                    column_name,
                    target_name,
                    self.color_options,
                )
            if column_type == "cat" and target_type == "num":
                feature_by_target_figure = plot_boxes(
                    metric_result.plot_data.data_by_target.data_for_plots["current"],
                    ref_data_by_target,
                    target_name,
                    column_name,
                    self.color_options,
                )
            if column_type == "num" and target_type == "num":
                feature_by_target_figure = plot_num_num_rel(
                    metric_result.plot_data.data_by_target.data_for_plots["current"],
                    ref_data_by_target,
                    target_name,
                    column_name,
                    color_options=self.color_options,
                )
            if column_type == "cat" and target_type == "cat":
                feature_by_target_figure = plot_cat_cat_rel(
                    metric_result.plot_data.data_by_target.data_for_plots["current"],
                    ref_data_by_target,
                    target_name,
                    column_name,
                    color_options=self.color_options,
                )

            additional_graphs.append(
                AdditionalGraphInfo(
                    column_name + "_by_target",
                    {
                        "data": feature_by_target_figure["data"],
                        "layout": feature_by_target_figure["layout"],
                    },
                )
            )
            parts.append({"title": column_name + " by target", "id": column_name + "_by_target"})

        wi = BaseWidgetInfo(
            type="rich_data",
            title="",
            size=2,
            params={
                "header": metric_result.column_name,
                "description": column_type,
                "metricsValuesHeaders": metrics_values_headers,
                "metrics": self._metrics_fot_table(column_type, metric_result),
                "graph": {"data": fig["data"], "layout": fig["layout"]},
                "details": {"parts": parts, "insights": []},
            },
            additionalGraphs=additional_graphs,
        )
        return [wi]

    @staticmethod
    def _get_stats_with_names(
        stats_list: List[Tuple[str, str, Optional[str]]],
        current_stats: ColumnCharacteristics,
        reference_stats: Optional[ColumnCharacteristics],
    ) -> List[dict]:
        def get_values_as_string(stats_dict, field_name, field_percentage_name) -> str:
            field_value = stats_dict[field_name]

            if field_value is None:
                field_value = ""

            if field_percentage_name is None:
                return str(field_value)

            else:
                return f"{field_value} ({stats_dict[field_percentage_name]}%)"

        result = []

        current_stats_dict = {
            field.name: getattr(current_stats, field.name) for field in dataclasses.fields(current_stats)
        }

        if reference_stats is None:
            reference_stats_dict = None

        else:
            reference_stats_dict = {
                field.name: getattr(reference_stats, field.name) for field in dataclasses.fields(reference_stats)
            }

        for stat_label, stat_field, stat_field_percentage in stats_list:
            values = [get_values_as_string(current_stats_dict, stat_field, stat_field_percentage)]

            if reference_stats_dict is not None:
                values.append(get_values_as_string(reference_stats_dict, stat_field, stat_field_percentage))

            result.append(
                {
                    "label": stat_label,
                    "values": values,
                }
            )
        return result

    def _metrics_fot_table(self, column_type: str, data_quality_results: ColumnSummary):
        current_stats = data_quality_results.current_characteristics

        reference_stats = None

        if data_quality_results.reference_characteristics is not None:
            reference_stats = data_quality_results.reference_characteristics

        metrics = []
        if column_type == "cat":
            # mapping for category stats: (label, field_name_for_main_value, field_name_for_percentage)
            cat_features = [
                ("count", "count", None),
                ("unique", "unique", "unique_percentage"),
                ("most common", "most_common", "most_common_percentage"),
                ("missing", "missing", "missing_percentage"),
            ]

            if reference_stats:
                cat_features.append(("new categories", "new_in_current_values_count", None))
                cat_features.append(("missing categories", "unused_in_current_values_count", None))

            metrics.extend(self._get_stats_with_names(cat_features, current_stats, reference_stats))

        elif column_type == "num":
            # mapping for num stats: (label, field_name_for_main_value, field_name_for_percentage)
            num_features = [
                ("count", "count", None),
                ("mean", "mean", None),
                ("std", "std", None),
                ("min", "min", None),
                ("25%", "p25", None),
                ("50%", "p50", None),
                ("75%", "p75", None),
                ("max", "max", None),
                ("unique", "unique", "unique_percentage"),
                ("most common", "most_common", "most_common_percentage"),
                ("missing", "missing", "missing_percentage"),
                ("infinite", "infinite_count", "infinite_percentage"),
            ]
            metrics.extend(self._get_stats_with_names(num_features, current_stats, reference_stats))

        elif column_type == "datetime":
            # mapping for datetime stats: (label, field_name_for_main_value, field_name_for_percentage)
            datetime_features = [
                ("count", "count", None),
                ("unique", "unique", "unique_percentage"),
                ("most common", "most_common", "most_common_percentage"),
                ("missing", "missing", "missing_percentage"),
                ("first", "first", None),
                ("last", "last", None),
            ]
            metrics.extend(self._get_stats_with_names(datetime_features, current_stats, reference_stats))

        return metrics
