// pqdif2csv — convert a PQDIF (IEEE 1159.3) file to a long-format CSV of ONLY frequency + voltage.
//
// Usage:   pqdif2csv <file.pqd>            (writes CSV to stdout)
//          pqdif2csv <file.pqd> <out.csv>  (writes CSV to a file)
//
// Output contract (consumed by survey_ingest/parsers.py :: parse_pqdif):
//   header:  timestamp,phase,channel,value
//   channel: "frequency" | "voltage"   (nothing else is ever emitted)
//   phase:   L1 | L2 | L3 | 1p
//   timestamp: ISO-8601 UTC, e.g. 2026-01-01T00:00:00.000Z
//
// This is the ONLY component that understands the PQDIF binary format. It exists so the dependency-
// light Python worker can support PQDIF by shelling out, without a Python binary parser. By filtering
// to Voltage(RMS/Instantaneous) + Frequency here, the "only frequency and voltage leave" guarantee
// holds for the binary path too — current, power, harmonics/THD and everything else are never written.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using GSF.PQDIF.Logical;

namespace GridWitness.Pqdif2Csv
{
    internal static class Program
    {
        // Static Guid identifiers from GSF, resolved once.
        private static readonly Guid TimeSeries = SeriesValueType.Time;
        private static readonly Guid ValueSeries = SeriesValueType.Val;
        private static readonly Guid FrequencyChar = QuantityCharacteristic.Frequency;
        private static readonly Guid RmsChar = QuantityCharacteristic.RMS;
        private static readonly Guid InstChar = QuantityCharacteristic.Instantaneous;

        private static int Main(string[] args)
        {
            if (args.Length < 1)
            {
                Console.Error.WriteLine("usage: pqdif2csv <file.pqd> [out.csv]");
                return 2;
            }

            string inputPath = args[0];
            if (!File.Exists(inputPath))
            {
                Console.Error.WriteLine("pqdif2csv: file not found: " + inputPath);
                return 2;
            }

            TextWriter output = args.Length >= 2
                ? new StreamWriter(args[1], false, new UTF8Encoding(false))
                : Console.Out;

            try
            {
                output.WriteLine("timestamp,phase,channel,value");
                int rows = Convert(inputPath, output);
                output.Flush();
                Console.Error.WriteLine("pqdif2csv: wrote " + rows + " frequency/voltage rows");
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("pqdif2csv: failed to parse " + inputPath + ": " + ex.Message);
                return 1;
            }
            finally
            {
                if (output != Console.Out)
                    output.Dispose();
            }
        }

        private static int Convert(string inputPath, TextWriter output)
        {
            int rows = 0;
            using (var parser = new LogicalParser(inputPath))
            {
                parser.Open();
                while (parser.HasNextObservationRecord())
                {
                    ObservationRecord record = parser.NextObservationRecord();
                    foreach (ChannelInstance channel in record.ChannelInstances)
                    {
                        SeriesInstance? timeSeries = channel.SeriesInstances
                            .FirstOrDefault(s => s.Definition.ValueTypeID == TimeSeries);
                        if (timeSeries == null)
                            continue;

                        DateTime[] times = ResolveTimes(record, timeSeries);
                        string phase = MapPhase(channel.Definition.Phase);
                        bool isVoltage = channel.Definition.QuantityMeasured == QuantityMeasured.Voltage;

                        foreach (SeriesInstance series in channel.SeriesInstances)
                        {
                            if (series.Definition.ValueTypeID != ValueSeries)
                                continue;

                            Guid characteristic = series.Definition.QuantityCharacteristicID;
                            string? channelName = null;
                            if (characteristic == FrequencyChar)
                                channelName = "frequency";
                            else if (isVoltage && (characteristic == RmsChar || characteristic == InstChar))
                                channelName = "voltage";
                            if (channelName == null)
                                continue; // not RMS/instantaneous voltage or frequency — dropped at source

                            rows += Emit(output, times, series.OriginalValues, phase, channelName);
                        }
                    }
                }
            }
            return rows;
        }

        private static int Emit(TextWriter output, DateTime[] times, IList<object> values, string phase, string channel)
        {
            int n = Math.Min(times.Length, values.Count);
            int written = 0;
            for (int i = 0; i < n; i++)
            {
                if (!TryToDouble(values[i], out double v))
                    continue;
                output.Write(times[i].ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ", CultureInfo.InvariantCulture));
                output.Write(',');
                output.Write(phase);
                output.Write(',');
                output.Write(channel);
                output.Write(',');
                output.WriteLine(v.ToString("R", CultureInfo.InvariantCulture));
                written++;
            }
            return written;
        }

        private static string MapPhase(Phase phase)
        {
            switch (phase)
            {
                case Phase.AN: case Phase.Residual: return "L1";
                case Phase.BN: return "L2";
                case Phase.CN: return "L3";
                default: return "1p";
            }
        }

        // The time series is usually seconds-offset from the record's start time, but some writers
        // store absolute DateTimes or TimeSpans. Handle all three.
        private static DateTime[] ResolveTimes(ObservationRecord record, SeriesInstance timeSeries)
        {
            DateTime start = record.StartTime;
            IList<object> raw = timeSeries.OriginalValues;
            var times = new DateTime[raw.Count];
            for (int i = 0; i < raw.Count; i++)
            {
                object value = raw[i];
                if (value is DateTime dt)
                    times[i] = dt;
                else if (value is TimeSpan ts)
                    times[i] = start + ts;
                else if (TryToDouble(value, out double secs))
                    times[i] = start.AddSeconds(secs);
                else
                    times[i] = start;
            }
            return times;
        }

        private static bool TryToDouble(object value, out double result)
        {
            try
            {
                result = System.Convert.ToDouble(value, CultureInfo.InvariantCulture);
                return !double.IsNaN(result) && !double.IsInfinity(result);
            }
            catch
            {
                result = 0;
                return false;
            }
        }
    }
}
