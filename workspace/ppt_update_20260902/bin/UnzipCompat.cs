using System;
using System.IO;
using System.IO.Compression;
using System.Linq;

public static class UnzipCompat
{
    public static int Main(string[] args)
    {
        if (args.Length < 2 || (args[0] != "-Z1" && args[0] != "-p"))
        {
            Console.Error.WriteLine("usage: unzip -Z1 file | unzip -p file entry");
            return 2;
        }

        using (var archive = ZipFile.OpenRead(args[1]))
        {
            if (args[0] == "-Z1")
            {
                foreach (var entry in archive.Entries)
                    Console.Out.WriteLine(entry.FullName);
                return 0;
            }

            if (args.Length < 3)
                return 2;
            var target = archive.Entries.FirstOrDefault(e => e.FullName == args[2]);
            if (target == null)
            {
                Console.Error.WriteLine("entry not found: " + args[2]);
                return 1;
            }
            using (var input = target.Open())
            using (var output = Console.OpenStandardOutput())
                input.CopyTo(output);
        }
        return 0;
    }
}
