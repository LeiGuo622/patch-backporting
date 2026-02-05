import argparse
import logging
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir_path = os.path.join(parent_dir, "src")
sys.path.append(src_dir_path)

from backporting import load_yml
from tools.logger import logger
from tools.project import Project
from tools.utils import revise_patch


def main():
    """
    For generated patch, use this file to validate the patch if it could compile, pass test and poc.
    """
    # parse arguments
    parser = argparse.ArgumentParser(
        description="Backports patch with the help of LLM",
        usage="%(prog)s --config CONFIG.yml\ne.g.: python %(prog)s --config CVE-examaple.yml",
    )
    parser.add_argument(
        "-c", "--config", type=str, required=True, help="CVE config yml"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug mode")
    args = parser.parse_args()
    debug_mode = args.debug
    config_file = args.config
    if debug_mode:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Initialize: load config, create project and get sh file in dataset
    data = load_yml(config_file)
    for file in os.listdir(data.patch_dataset_dir):
        if os.path.exists(f"{data.project_dir}{file}"):
            os.remove(f"{data.project_dir}{file}")
        os.symlink(f"{data.patch_dataset_dir}{file}", f"{data.project_dir}{file}")
    project = Project(data)

    # HACK: call func to test patch here, for example, I call `_validate`
    revised_patch, _ = revise_patch(patch, project.dir)
    project.all_hunks_applied_succeeded = True
    project._validate(data.target_release, revised_patch)
    if project.poc_succeeded:
        logger.info(
            f"Patch successfully passes validation on target release {data.target_release}"
        )
    else:
        logger.error(
            f"Patch failed to pass validation on target release {data.target_release}"
        )


if __name__ == "__main__":
    # HACK: put the patch here
    patch = """
diff --git a/net/tipc/link.c b/net/tipc/link.c
index 8d9e09f48f4ca1..1e14d7f8f28f1d 100644
--- a/net/tipc/link.c
+++ b/net/tipc/link.c
@@ -2200,7 +2200,7 @@ static int tipc_link_proto_rcv(struct tipc_link *l, struct sk_buff *skb,
 	struct tipc_msg *hdr = buf_msg(skb);
 	struct tipc_gap_ack_blks *ga = NULL;
 	bool reply = msg_probe(hdr), retransmitted = false;
-	u16 dlen = msg_data_sz(hdr), glen = 0;
+	u32 dlen = msg_data_sz(hdr), glen = 0;
 	u16 peers_snd_nxt =  msg_next_sent(hdr);
 	u16 peers_tol = msg_link_tolerance(hdr);
 	u16 peers_prio = msg_linkprio(hdr);
@@ -2214,6 +2214,10 @@ static int tipc_link_proto_rcv(struct tipc_link *l, struct sk_buff *skb,
 	void *data;
 
 	trace_tipc_proto_rcv(skb, false, l->name);
+
+	if (dlen > U16_MAX)
+		goto exit;
+
 	if (tipc_link_is_blocked(l) || !xmitq)
 		goto exit;
 
@@ -2309,7 +2313,8 @@ static int tipc_link_proto_rcv(struct tipc_link *l, struct sk_buff *skb,
 
 		/* Receive Gap ACK blocks from peer if any */
 		glen = tipc_get_gap_ack_blks(&ga, l, hdr, true);
-
+		if(glen > dlen)
+			break;
 		tipc_mon_rcv(l->net, data + glen, dlen - glen, l->addr,
 			     &l->mon_state, l->bearer_id);
 
diff --git a/net/tipc/monitor.c b/net/tipc/monitor.c
index 407619697292f3..2f4d23238a7e33 100644
--- a/net/tipc/monitor.c
+++ b/net/tipc/monitor.c
@@ -496,6 +496,8 @@ void tipc_mon_rcv(struct net *net, void *data, u16 dlen, u32 addr,
 	state->probing = false;
 
 	/* Sanity check received domain record */
+	if (new_member_cnt > MAX_MON_DOMAIN)
+		return;
 	if (dlen < dom_rec_len(arrv_dom, 0))
 		return;
 	if (dlen != dom_rec_len(arrv_dom, new_member_cnt))
"""
    main()
