using System;
using System.IO;
using System.IO.Compression;

public static class UnzipShim
{
    public static int Main(string[] args)
    {
        if (args.Length < 2) return 2;
        string mode = args[0];
        string zipPath = args[1];
        using (ZipArchive archive = ZipFile.OpenRead(zipPath))
        {
            if (mode == "-Z1")
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                    Console.Out.WriteLine(entry.FullName);
                return 0;
            }
            if (mode == "-p" && args.Length >= 3)
            {
                ZipArchiveEntry entry = archive.GetEntry(args[2]);
                if (entry == null) return 11;
                using (Stream input = entry.Open())
                using (Stream output = Console.OpenStandardOutput())
                    input.CopyTo(output);
                return 0;
            }
        }
        return 2;
    }
}
