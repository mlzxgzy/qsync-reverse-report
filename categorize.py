funcs=set(l.split('\t')[0] for l in open("qsync-analysis/out/func_inventory.txt") if l.strip())
assign={}
def put(cat, names):
    for n in names:
        if n in funcs:
            assert n not in assign, f"dup {n}"
            assign[n]=cat
put('登录/会话',['login','logout','activate','passwordless','qbox_auth_config_password'])
put('鉴权(共享文件夹两步)',['auth_1','auth_2','sharefolder_auth_1','sharefolder_auth_2'])
put('会话状态/探测',['check_alive','info','get_sys_setting','get_ad_info','get_move_status','daemon_list',
  'get_domain_ip_list','qbox_get_qbox_info','qbox_get_nas_status','qbox_get_static_information',
  'qbox_get_quota_info','qbox_get_nas_uid','qbox_get_system_sid','qbox_get_policy','qbox_get_config_acl',
  'qbox_get_veto_files','qbox_get_recycle_bin_status','qbox_get_last_modify_time','qbox_get_registry',
  'qbox_get_cluster_node_list','qbox_get_syncing_folder_list','qbox_get_user_home','qbox_get_progress'])
put('变更发现(日志游标)',['qbox_get_max_log','qbox_get_sync_log','qbox_query_notify','qbox_get_device_config_list',
  'qbox_get_device_config','qbox_save_device_config','qbox_reset_device_config','qbox_write_log',
  'qbox_sync_start','qbox_sync_done','qbox_get_my_event','qbox_remove_event'])
put('列举/元数据',['get_list','get_tree','stat','properties','get_thumb','qbox_check_permission',
  'check_file_present','check_permission'])
put('写操作',['createdir','rename','move','delete','trash_recovery','repository_recovery',
  'qbox_fix_team_folder_link','qbox_set_recycle_bin','qbox_set_policy','qbox_rename_device'])
put('上传',['start_chunked_upload','chunked_upload','get_chunked_upload_status','delete_chunked_upload_file',
  'upload','upload_and_move'])
put('下载',['download','download_file'])
put('版本化/delta',sorted(f for f in funcs if f.startswith('versioning')))
put('共享/团队文件夹',sorted(f for f in funcs if f.startswith(('qbox_share','qbox_unshare','qbox_team_folder',
  'qbox_accept','qbox_deny','qbox_leave','qbox_kickout','qbox_find_share','get_share','share_file',
  'update_link','update_share_link','send_share_mail','qbox_get_share','qbox_get_user_list','delete_share',
  'qbox_set_share_member'))))
put('备份',sorted(f for f in funcs if f.startswith(('qbox_backup','qbox_check_backup','qbox_set_backup',
  'qbox_clean_backup','qbox_remove_backup','get_backup_file_list'))))
put('其他',['qpkg','search_engine'])
from collections import Counter
c=Counter(assign.values())
order=['登录/会话','鉴权(共享文件夹两步)','会话状态/探测','变更发现(日志游标)','列举/元数据','写操作',
       '上传','下载','版本化/delta','共享/团队文件夹','备份','其他']
for k in order: print(f"| {k} | {c[k]} |")
rest=funcs-set(assign)
print("未归类:", sorted(rest), "| 合计:", len(assign)+len(rest), "/ 总数:", len(funcs))
