ObjC.import("Foundation");

function run(args) {
    const url = $.NSURL.fileURLWithPath(args[0]);
    const error = Ref();
    const values = url.resourceValuesForKeysError($([
        $.NSURLIsAliasFileKey,
        $.NSURLIsUbiquitousItemKey,
        $.NSURLUbiquitousItemDownloadingStatusKey,
        $.NSURLUbiquitousItemHasUnresolvedConflictsKey
    ]), error);
    const metadata = ObjC.deepUnwrap(values);
    if (!metadata) {
        const problem = error[0];
        return JSON.stringify({ error: problem ? Number(problem.code) : 0 });
    }
    const states = [
        [$.NSURLUbiquitousItemDownloadingStatusCurrent, "current"],
        [$.NSURLUbiquitousItemDownloadingStatusDownloaded, "stale"],
        [$.NSURLUbiquitousItemDownloadingStatusNotDownloaded, "not_downloaded"]
    ];
    const observed = metadata.NSURLUbiquitousItemDownloadingStatusKey;
    const match = states.find(([key]) => ObjC.unwrap(key) === observed);
    return JSON.stringify({
        alias: metadata.NSURLIsAliasFileKey === true,
        conflict: metadata.NSURLUbiquitousItemHasUnresolvedConflictsKey === true,
        cloud: metadata.NSURLIsUbiquitousItemKey === true || Boolean(match),
        download: match ? match[1] : null
    });
}
