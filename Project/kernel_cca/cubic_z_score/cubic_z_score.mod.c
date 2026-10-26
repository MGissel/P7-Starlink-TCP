#include <linux/module.h>
#include <linux/export-internal.h>
#include <linux/compiler.h>

MODULE_INFO(name, KBUILD_MODNAME);

__visible struct module __this_module
__section(".gnu.linkonce.this_module") = {
	.name = KBUILD_MODNAME,
	.init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
	.exit = cleanup_module,
#endif
	.arch = MODULE_ARCH_INIT,
};



static const struct modversion_info ____versions[]
__used __section("__versions") = {
	{ 0xe8213e80, "_printk" },
	{ 0x90a48d82, "__ubsan_handle_out_of_bounds" },
	{ 0xd0a60ac9, "tcp_slow_start" },
	{ 0x8db9b6ac, "__usecs_to_jiffies" },
	{ 0x13a85c69, "tcp_cong_avoid_ai" },
	{ 0x82fd7238, "__ubsan_handle_shift_out_of_bounds" },
	{ 0x9c76a50e, "tcp_unregister_congestion_control" },
	{ 0x3de7af71, "tcp_reno_undo_cwnd" },
	{ 0xcc1d5ac5, "param_ops_int" },
	{ 0xd272d446, "__fentry__" },
	{ 0xd272d446, "__x86_return_thunk" },
	{ 0x058c185a, "jiffies" },
	{ 0x30eb81ed, "__dynamic_pr_debug" },
	{ 0xd272d446, "dump_stack" },
	{ 0xa67ce064, "register_btf_kfunc_id_set" },
	{ 0x6a21d36b, "tcp_register_congestion_control" },
	{ 0xe9196a28, "module_layout" },
};

static const u32 ____version_ext_crcs[]
__used __section("__version_ext_crcs") = {
	0xe8213e80,
	0x90a48d82,
	0xd0a60ac9,
	0x8db9b6ac,
	0x13a85c69,
	0x82fd7238,
	0x9c76a50e,
	0x3de7af71,
	0xcc1d5ac5,
	0xd272d446,
	0xd272d446,
	0x058c185a,
	0x30eb81ed,
	0xd272d446,
	0xa67ce064,
	0x6a21d36b,
	0xe9196a28,
};
static const char ____version_ext_names[]
__used __section("__version_ext_names") =
	"_printk\0"
	"__ubsan_handle_out_of_bounds\0"
	"tcp_slow_start\0"
	"__usecs_to_jiffies\0"
	"tcp_cong_avoid_ai\0"
	"__ubsan_handle_shift_out_of_bounds\0"
	"tcp_unregister_congestion_control\0"
	"tcp_reno_undo_cwnd\0"
	"param_ops_int\0"
	"__fentry__\0"
	"__x86_return_thunk\0"
	"jiffies\0"
	"__dynamic_pr_debug\0"
	"dump_stack\0"
	"register_btf_kfunc_id_set\0"
	"tcp_register_congestion_control\0"
	"module_layout\0"
;

MODULE_INFO(depends, "");


MODULE_INFO(srcversion, "4DE3C59285A5D4C62C6E2F8");
