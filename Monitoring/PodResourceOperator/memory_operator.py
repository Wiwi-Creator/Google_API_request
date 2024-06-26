from pathlib import Path
from pytz import timezone, utc
from Monitoring.configs import MonitoringAPI, MonitoringTableID
import logging
from google.cloud import monitoring_v3
from google.cloud.monitoring_v3.types import TimeInterval
from Monitoring.utils.exporter import BigqueryExporterBase


class MemoryOperator:
    def __init__(self, start_timestamp, end_timestamp):
        self.client = monitoring_v3.MetricServiceClient()
        self.project_id = "datapool-1806"
        self.project_name = f"projects/{self.project_id}"
        self.interval = TimeInterval()
        # Create Timestamps for start and end time
        self.interval.start_time = start_timestamp
        self.interval.end_time = end_timestamp

    def run(self):

        metric_types = [
            ("memory_request_bytes", MonitoringAPI.memory_request_bytes_url, MonitoringTableID.memory_request_table, 'int64_value'),
            ("memory_used_bytes", MonitoringAPI.memory_used_bytes_url, MonitoringTableID.memory_used_table, 'int64_value'),
            ("memory_request_utilization", MonitoringAPI.memory_request_utilization_url, MonitoringTableID.memory_utilization_table, 'double_value')
        ]

        for metric_name, metric_url, table_id, value_type in metric_types:
            schema_path = Path(__file__).parent / f"schemas/{table_id}.json"
            filter_string = self._get_filter(metric_url)
            results = self._get_results(self.interval, filter_string)
            pod_info = self._get_memory_pod_info(results, metric_name, value_type)

            bq_operator = BigqueryExporterBase(projectID=self.project_id)
            logging.info(f"Updating table {table_id} with {len(pod_info)} rows.")

            bq_operator.update_table_using_replace(data=pod_info,
                                                   schema_path=schema_path,
                                                   datasetID='GKE_monitor_raw',
                                                   tableID=table_id)

    def _get_filter(self, metric_url):
        filter_string = (
            f'metric.type = "{metric_url}" '
            'AND resource.type = "k8s_container" '
            'AND resource.labels.namespace_name = "default" '
            )
        return filter_string

    def _get_results(self, interval, filter_string):
        #註解為可以根據時間作aggregate , 預設是每60秒計算一筆record
        #aggregation = monitoring_v3.Aggregation(
        #    {
        #        "alignment_period": {"seconds": 1200},  # 20 minutes
        #        "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        #        }
        #    )

        results = self.client.list_time_series(
            request={
                "name": self.project_name,
                "filter": filter_string,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL
                #,"aggregation": aggregation
            }
        )
        return results

    def _get_memory_pod_info(self, results, metric_type, value_type):
        memory_pod_info = []
        for result in results:
            for point in result.points:
                metric_value = getattr(point.value, value_type)
                memory_pod_info.append({
                    'Pod_name': result.resource.labels["pod_name"],
                    'Namespace': result.resource.labels["namespace_name"],
                    'Container_Name': result.resource.labels["container_name"],
                    'Memory_type': result.metric.labels.get('memory_type', 'None'),
                    'Execute_Time': point.interval.start_time.replace(tzinfo=utc).astimezone(timezone('Asia/Taipei')).strftime('%Y-%m-%dT%H:%M:%S'),
                    metric_type: metric_value
                })
        return memory_pod_info
