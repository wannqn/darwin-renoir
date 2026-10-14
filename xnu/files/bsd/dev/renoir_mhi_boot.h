/* Renoir WCN6855 BHI bring-up. Included by redwood_wifi.c after its SMMU
 * and PCIe power helpers. Explicit probe only, never ordinary wifi=1.
 * Protocol/layout: OKX drivers/bus/mhi/core/mhi_boot.c, mhi_internal.h,
 * and pci-msm.c. The ROM authenticates the device's original signed image.
 */
#define RENOIR_BHI_SIZE 0x80000u
#include "renoir_mhi_protocol.h"
extern vm_offset_t ml_io_map_unmappable(vm_offset_t phys_addr, vm_size_t size, unsigned int flags);
static struct {
	bool context_saved, sid_saved, active;
	vm_offset_t buffer, parf, tlmm;
	uint32_t allocation, firmware_size, target_extra, bhi_offset, bhie_offset;
	vm_offset_t control_alias;
	uint32_t control, event_db, ee, event_count;
	uint64_t event_rp[2], command_expected;
	uint32_t command_result, channel_db, rx_slot, rx_packets;
	uint64_t rx_expected, tx_expected;
	bool tx_done, reply_seen, reply_ok, memory_ready, resume_pending, firmware_ready;
	uint32_t resume_node, resume_port, resume_local_node, resume_local_port;
	uint32_t wlfw_node, wlfw_port, qmi_message, qmi_transaction, tx_slot;
	uint32_t memory_count, memory_sizes[52], memory_types[52], memory_used;
	uint32_t board_id, soc_version, chip_id, chip_family;
	uint32_t context[9], cbar, cba2r, sid_cfg, sid_table[256];
} renoir_bhi;
static const uint32_t renoir_bhi_cb_offsets[] = { 0,0x10,0x20,0x24,0x28,0x2c,0x30,0x38,0x3c };

static void
renoir_bhi_host(vm_offset_t parf, vm_offset_t tlmm)
{
	bzero(&renoir_bhi,sizeof(renoir_bhi));
	renoir_bhi.board_id=0xff;
	renoir_bhi.parf=parf; renoir_bhi.tlmm=tlmm;
}

/* Caller must have asserted PERST before returning an active mapping.
 * In panic context no allocations are freed; reset still stops the device.
 */
static void
renoir_bhi_cleanup(bool free_buffer)
{
	bool restored=true, changed=renoir_bhi.context_saved||renoir_bhi.sid_saved;
	if (renoir_bhi.context_saved) {
		radio_space_off();
		wr(apps_smmu.base+SMMU_SMR(radio_space.match),radio_space.old_smr);
		wr(apps_smmu.base+SMMU_S2CR(radio_space.match),radio_space.old_s2cr);
		wr(apps_smmu_context.base,0);
		wr(apps_smmu_context.base+SMMU_CB_FSR,rd(apps_smmu_context.base+SMMU_CB_FSR)&SMMU_FSR_ALL);
		for (unsigned i=1; i<9; i++) { wr(apps_smmu_context.base+renoir_bhi_cb_offsets[i],renoir_bhi.context[i]); }
		wr(apps_smmu_second.base+SMMU_CBAR(radio_space.context),renoir_bhi.cbar);
		wr(apps_smmu_second.base+SMMU_CBA2R(radio_space.context),renoir_bhi.cba2r);
		wr(apps_smmu_context.base,renoir_bhi.context[0]);
		for (unsigned i=0; i<9; i++) {
			if (rd(apps_smmu_context.base+renoir_bhi_cb_offsets[i])!=renoir_bhi.context[i]) { restored=false; }
		}
		if (rd(apps_smmu.base+SMMU_SMR(radio_space.match))!=radio_space.old_smr ||
		    rd(apps_smmu.base+SMMU_S2CR(radio_space.match))!=radio_space.old_s2cr ||
		    rd(apps_smmu_second.base+SMMU_CBAR(radio_space.context))!=renoir_bhi.cbar ||
		    rd(apps_smmu_second.base+SMMU_CBA2R(radio_space.context))!=renoir_bhi.cba2r) { restored=false; }
		renoir_bhi.context_saved=false;
	}
	if (renoir_bhi.sid_saved) {
		for (unsigned i=0; i<256; i++) { wr(renoir_bhi.parf+0x2000+4*i,renoir_bhi.sid_table[i]); }
		wr(renoir_bhi.parf+0x2c00,renoir_bhi.sid_cfg);
		for (unsigned i=0; i<256; i++) {
			if (rd(renoir_bhi.parf+0x2000+4*i)!=renoir_bhi.sid_table[i]) { restored=false; }
		}
		if (rd(renoir_bhi.parf+0x2c00)!=renoir_bhi.sid_cfg) { restored=false; }
		renoir_bhi.sid_saved=false;
	}
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_bhi.active=false;
	if (changed) { say("renoir-wifi: BHI SMMU/BDF configuration restored %u\n",restored); }
	if (free_buffer && renoir_bhi.buffer) {
		if (renoir_bhi.control_alias) {
			ml_io_unmap(renoir_bhi.control_alias,0x10000);
			renoir_bhi.control_alias=0;
		}
		kmem_free(kernel_map,renoir_bhi.buffer,renoir_bhi.allocation);
		renoir_bhi.buffer=0;
	}
}

static void
renoir_mhi_quiesce(void)
{
	if (!renoir_bhi.active && !renoir_bhi.context_saved && !renoir_bhi.sid_saved) { return; }
	wr(renoir_bhi.tlmm+94*0x1000+4,0);
	wr(renoir_bhi.tlmm+64*0x1000+4,0);
	__asm__ volatile("dsb sy" ::: "memory");
	sleep_us(1000);
	renoir_bhi_cleanup(false);
}

static bool
renoir_bhi_prepare(const uint8_t *firmware, uint32_t size, bool full)
{
	if (!renoir_bhi.parf || !renoir_bhi.tlmm || !radio_space_find()) { return false; }
	if (rd(apps_smmu_context.base+SMMU_CB_FSR)&SMMU_FSR_ALL) { return false; }
	renoir_bhi.firmware_size=full ? size : RENOIR_BHI_SIZE;
	renoir_bhi.allocation=round_page(renoir_bhi.firmware_size)+(full ? 0x10000 : 0)+renoir_bhi.target_extra;
	if (kmem_alloc_contig(kernel_map,&renoir_bhi.buffer,renoir_bhi.allocation,0,0,0,
	    KMA_KOBJECT|KMA_ZERO|KMA_DATA,VM_KERN_MEMORY_IOKIT)!=KERN_SUCCESS) {
		say("renoir-wifi: BHI has no contiguous firmware buffer\n"); return false;
	}
	uint64_t physical=kvtophys(renoir_bhi.buffer);
	if ((physical&4095) || physical+renoir_bhi.allocation>(1ull<<36)) { return false; }
	for (uint32_t offset=0; offset<renoir_bhi.allocation; offset+=16384) {
		if (kvtophys(renoir_bhi.buffer+offset)!=physical+offset) {
			say("renoir-wifi: firmware allocation is not contiguous at %#x\n",offset);return false;
		}
	}
	memcpy((void *)renoir_bhi.buffer,firmware,renoir_bhi.firmware_size);
	for (vm_offset_t line=renoir_bhi.buffer; line<renoir_bhi.buffer+renoir_bhi.allocation; line+=64) {
		__asm__ volatile("dc civac, %0" : : "r"(line) : "memory");
	}
	__asm__ volatile("dsb sy" ::: "memory");
	if (!radio_enter(RADIO_ADDRESSES,physical,renoir_bhi.allocation,RADIO_PTE)) { return false; }
	for (unsigned i=0; i<9; i++) { renoir_bhi.context[i]=rd(apps_smmu_context.base+renoir_bhi_cb_offsets[i]); }
	renoir_bhi.cbar=rd(apps_smmu_second.base+SMMU_CBAR(radio_space.context));
	renoir_bhi.cba2r=rd(apps_smmu_second.base+SMMU_CBA2R(radio_space.context));
	renoir_bhi.context_saved=true;
	if (!radio_space_on_for(0x2401,0)) { return false; }
	renoir_bhi.sid_cfg=rd(renoir_bhi.parf+0x2c00);
	for (unsigned i=0; i<256; i++) { renoir_bhi.sid_table[i]=rd(renoir_bhi.parf+0x2000+4*i); }
	renoir_bhi.sid_saved=true;
	for (unsigned i=0; i<256; i++) { wr(renoir_bhi.parf+0x2000+4*i,0); }
	/* CRC8(poly 0x07, init 0) of big-endian BDF 0x0100 is 0x15.
 * Entry: BDF[31:16] | relative SID[15:8] | next[7:0]. */
	wr(renoir_bhi.parf+0x2000+4*0x15,0x01000100);
	wr(renoir_bhi.parf+0x2c00,renoir_bhi.sid_cfg&~1u);
	__asm__ volatile("dsb sy" ::: "memory");
	if (rd(renoir_bhi.parf+0x2000+4*0x15)!=0x01000100 || (rd(renoir_bhi.parf+0x2c00)&1)) {
		say("renoir-wifi: PCIe BDF-to-SID programming refused\n");return false;
	}
	say("renoir-wifi: BHI DMA buffer %#llx -> IOVA %#llx, %u KiB, SID 0x2401\n",physical,RADIO_ADDRESSES,renoir_bhi.allocation/1024);
	return true;
}

/* Context ABI aligns 64-bit pointers to four bytes. Access the uncached
 * alias with aligned words, including on platforms that trap unaligned I/O. */
static uint64_t
renoir_mhi_read64(vm_offset_t address)
{
	return (uint64_t)rd(address) | (uint64_t)rd(address+4)<<32;
}

static void
renoir_mhi_write64(vm_offset_t address, uint64_t value)
{
	wr(address+4,(uint32_t)(value>>32)); wr(address,(uint32_t)value);
}

static void
renoir_mhi_post_rx(vm_offset_t bar)
{
	uint64_t control=RADIO_ADDRESSES+renoir_bhi.control;
	unsigned slot=renoir_bhi.rx_slot;
	vm_offset_t tre=renoir_bhi.control_alias+0xb000+slot*16;
	renoir_mhi_write64(tre,control+0xc000); wr(tre+8,8192); wr(tre+12,0x20300);
	renoir_bhi.rx_expected=control+0xb000+slot*16;
	renoir_bhi.rx_slot=(slot+1)%32;
	uint64_t next=control+0xb000+renoir_bhi.rx_slot*16;
	renoir_mhi_write64(renoir_bhi.control_alias+21*44+36,next);
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_mhi_write64(bar+renoir_bhi.channel_db+21*8,next);
}

static uint8_t
renoir_mhi_byte(vm_offset_t packet, unsigned offset)
{
	return rd(packet+(offset&~3u))>>((offset&3)*8);
}

static uint32_t
renoir_mhi_wire32(vm_offset_t packet, unsigned offset)
{
	uint32_t value=0;
	for (unsigned byte=0;byte<4;byte++) { value|=(uint32_t)renoir_mhi_byte(packet,offset+byte)<<(byte*8); }
	return value;
}

static void
renoir_mhi_memory_request(vm_offset_t packet, unsigned payload)
{
	/* QMI REQUEST_MEM: TLV 1 contains a u8 count followed by variable
	 * size/type/u8-config-count records and 13-byte configuration records. */
	if (payload<11 || renoir_mhi_byte(packet,39)!=1) { return; }
	unsigned size=renoir_mhi_byte(packet,40)|(renoir_mhi_byte(packet,41)<<8);
	if (size!=payload-10) { return; }
	unsigned count=renoir_mhi_byte(packet,42), offset=43, end=32+payload;
	if (!count || count>52) { return; }
	uint32_t sizes[52],types[52];
	for (unsigned i=0;i<count;i++) {
		if (end-offset<9) { return; }
		sizes[i]=renoir_mhi_wire32(packet,offset); types[i]=renoir_mhi_wire32(packet,offset+4);
		unsigned configs=renoir_mhi_byte(packet,offset+8);offset+=9;
		if (configs>2 || configs*13>end-offset) { return; }
		offset+=configs*13;
	}
	if (offset!=end) { return; }
	renoir_bhi.memory_count=count;
	for (unsigned i=0;i<count;i++) {
		renoir_bhi.memory_sizes[i]=sizes[i];renoir_bhi.memory_types[i]=types[i];
		say("renoir-wifi: firmware requests memory segment %u type %u size %#x\n",i,types[i],sizes[i]);
	}
}

static void
renoir_mhi_inspect_qrtr(vm_offset_t packet, unsigned length)
{
	if (length<32 || rd(packet)!=1 || rd(packet+20)>length-32) { return; }
	unsigned payload=rd(packet+20), type=rd(packet+4);
	if (rd(packet+16)) {
		renoir_bhi.resume_pending=true; renoir_bhi.resume_node=rd(packet+8); renoir_bhi.resume_port=rd(packet+12);
		renoir_bhi.resume_local_node=rd(packet+24);renoir_bhi.resume_local_port=rd(packet+28);
	}
	if (type==4 && payload>=20 && rd(packet+32)==4 && rd(packet+36)==0x45) {
		renoir_bhi.wlfw_node=rd(packet+44); renoir_bhi.wlfw_port=rd(packet+48);
		say("renoir-wifi: WLAN QMI service %#x instance %#x at %u:%u\n",rd(packet+36),rd(packet+40),renoir_bhi.wlfw_node,renoir_bhi.wlfw_port);
	}
	if (type!=1 || payload<7 || rd(packet+8)!=renoir_bhi.wlfw_node ||
	    rd(packet+12)!=renoir_bhi.wlfw_port || rd(packet+28)!=0x4000) { return; }
	if (renoir_mhi_byte(packet,32)==4 && payload==7 && !renoir_mhi_byte(packet,37) && !renoir_mhi_byte(packet,38) &&
	    !renoir_mhi_byte(packet,36) && (renoir_mhi_byte(packet,35)==0x38 || renoir_mhi_byte(packet,35)==0x21)) {
		renoir_bhi.firmware_ready=true;say("renoir-wifi: QMI firmware ready indication %#x\n",renoir_mhi_byte(packet,35));return;
	}
	if (renoir_mhi_byte(packet,32)==4 && payload==7 && !renoir_mhi_byte(packet,37) && !renoir_mhi_byte(packet,38) && renoir_mhi_byte(packet,35)==0x37 && renoir_mhi_byte(packet,36)==0) {
		renoir_bhi.memory_ready=true; say("renoir-wifi: QMI FW_MEM_READY received\n"); return;
	}
	if (renoir_mhi_byte(packet,32)==4 && renoir_mhi_byte(packet,35)==0x35 && renoir_mhi_byte(packet,36)==0) {
		unsigned bytes=renoir_mhi_byte(packet,37)|(renoir_mhi_byte(packet,38)<<8);
		if (bytes==payload-7) { renoir_mhi_memory_request(packet,payload); }
		return;
	}
	if (renoir_mhi_byte(packet,32)!=2 || ((uint32_t)renoir_mhi_byte(packet,33)|((uint32_t)renoir_mhi_byte(packet,34)<<8))!=renoir_bhi.qmi_transaction ||
	    ((uint32_t)renoir_mhi_byte(packet,35)|((uint32_t)renoir_mhi_byte(packet,36)<<8))!=renoir_bhi.qmi_message) { return; }
	unsigned bytes=renoir_mhi_byte(packet,37)|(renoir_mhi_byte(packet,38)<<8);
	if (bytes!=payload-7) { return; }
	bool saw_result=false, capability_ok=false;
	for (unsigned offset=39; offset<39+bytes;) {
		if (39+bytes-offset<3) { return; }
		unsigned tag=renoir_mhi_byte(packet,offset), size=renoir_mhi_byte(packet,offset+1)|(renoir_mhi_byte(packet,offset+2)<<8);
		offset+=3;
		if (size>39+bytes-offset) { return; }
		if (tag==2 && size==4) {
			if (saw_result) { return; }
			unsigned result=renoir_mhi_byte(packet,offset)|(renoir_mhi_byte(packet,offset+1)<<8);
			unsigned error=renoir_mhi_byte(packet,offset+2)|(renoir_mhi_byte(packet,offset+3)<<8);
			saw_result=true; capability_ok=result==0 && error==0;
			if (renoir_bhi.qmi_message!=0x25 || result || error) { say("renoir-wifi: QMI message %#x result %u error %u\n",renoir_bhi.qmi_message,result,error); }
		}
		if (renoir_bhi.qmi_message==0x24 && tag==0x10 && size==8) {
			renoir_bhi.chip_id=renoir_mhi_wire32(packet,offset); renoir_bhi.chip_family=renoir_mhi_wire32(packet,offset+4);
			say("renoir-wifi: chip ID %#x family %#x\n",renoir_bhi.chip_id,renoir_bhi.chip_family);
		}
		if (renoir_bhi.qmi_message==0x24 && tag==0x11 && size==4) {
			renoir_bhi.board_id=renoir_mhi_wire32(packet,offset);say("renoir-wifi: board ID %#x\n",renoir_bhi.board_id);
		}
		if (renoir_bhi.qmi_message==0x24 && tag==0x12 && size==4) {
			renoir_bhi.soc_version=renoir_mhi_wire32(packet,offset);say("renoir-wifi: SOC version %#x\n",renoir_bhi.soc_version);
		}
		if (renoir_bhi.qmi_message!=0x25) { say("renoir-wifi: QMI response TLV %#x length %u\n",tag,size); }
		offset+=size;
	}
	if (saw_result) { renoir_bhi.reply_seen=true; renoir_bhi.reply_ok=capability_ok; }
}

/* One RX buffer is outstanding: a checked completion transfers its ownership
 * back to the host. No packet pointer supplied by the device is dereferenced. */
static bool
renoir_mhi_ipcr_event(vm_offset_t bar, vm_offset_t entry, uint32_t data, uint32_t flags)
{
	unsigned channel=flags>>24, code=data>>24, length=data&65535;
	uint64_t completed=renoir_mhi_read64(entry);
	if (channel==20) {
		if (!renoir_bhi.tx_expected || completed!=renoir_bhi.tx_expected || code!=2) { return false; }
		renoir_bhi.tx_done=true;
		if (renoir_bhi.qmi_message!=0x25) { say("renoir-wifi: IPCR TX complete\n"); }
		return true;
	}
	if (channel!=21 || !renoir_bhi.rx_expected || completed!=renoir_bhi.rx_expected ||
	    (code!=2 && code!=4) || !length || length>8192) { return false; }
	vm_offset_t packet=renoir_bhi.control_alias+0xc000;
	__asm__ volatile("dsb sy" ::: "memory");
	if (renoir_qrtr_input) { renoir_qrtr_input((const uint8_t *)packet,length); }
	else { renoir_mhi_inspect_qrtr(packet,length); }
	renoir_bhi.rx_packets++;
	if (renoir_bhi.rx_packets<=8) {
		say("renoir-wifi: IPCR RX %u bytes packet %u\n",length,renoir_bhi.rx_packets);
		for (unsigned word=0;word<length/4 && word<13;word++) {
			say("renoir-wifi: QRTR word %u = %#x\n",word,rd(packet+word*4));
		}
	}
	renoir_mhi_post_rx(bar);
	return true;
}

/* Poll the coherent control alias. The firmware may report its new EE only
 * in an event, while BHI_EXECENV still holds SBL. Recycle entries as Linux's
 * mhi_recycle_ev_ring does, so the device never waits for an unacknowledged
 * control event. All pointers are checked before accessing DMA memory.
 */
static bool
renoir_mhi_poll_boot_events(vm_offset_t bar)
{
	volatile struct renoir_mhi_context *events=(void *)(renoir_bhi.control_alias+0x2000);
	for (unsigned ring=0; ring<2; ring++) {
		uint64_t base=RADIO_ADDRESSES+renoir_bhi.control+(ring ? 0x6000 : 0x5000);
		vm_offset_t context=renoir_bhi.control_alias+0x2000+ring*sizeof(*events);
		uint64_t length=ring ? 4096 : 512, producer=renoir_mhi_read64(context+28);
		if (producer<base || producer>=base+length || ((producer-base)&15)) {
			say("renoir-wifi: invalid MHI event %u producer %#llx\n",ring,producer);
			for (unsigned word=0; word<12; word++) { say("renoir-wifi: event context +%#x = %#x\n",word*4,rd(context+word*4)); }
			say("renoir-wifi: MHI CCABAP %#x %#x ECABAP %#x %#x CRCBAP %#x %#x CFG %#x status %#x\n",
			    rd(bar+0x5c),rd(bar+0x58),rd(bar+0x64),rd(bar+0x60),rd(bar+0x6c),rd(bar+0x68),rd(bar+0x10),rd(bar+0x48));
			for (unsigned word=0; word<16; word++) {
				say("renoir-wifi: event ring %u +%#x = %#x\n",ring,word*4,rd(renoir_bhi.control_alias+(ring ? 0x6000 : 0x5000)+word*4));
			}
			return false;
		}
		unsigned processed=0;
		while (renoir_bhi.event_rp[ring]!=producer && processed<length/16) {
			uint64_t local=renoir_bhi.event_rp[ring], wp=renoir_mhi_read64(context+36);
			if (local<base || local>=base+length || ((local-base)&15) ||
			    wp<base || wp>=base+length || ((wp-base)&15)) { return false; }
			vm_offset_t entry=renoir_bhi.control_alias+(local-RADIO_ADDRESSES-renoir_bhi.control);
			__asm__ volatile("dsb sy" ::: "memory");
			uint32_t data=rd(entry+8), flags=rd(entry+12), type=(flags>>16)&255, value=data>>24;
			if (renoir_bhi.event_count++<32) {
				say("renoir-wifi: MHI event ring %u type %#x data %#x flags %#x\n",ring,type,data,flags);
			}
			if (type==0x22 && !renoir_mhi_ipcr_event(bar,entry,data,flags)) { return false; }
			if (type==0x21) {
				uint64_t completed=renoir_mhi_read64(entry);
				if (!renoir_bhi.command_expected || completed!=renoir_bhi.command_expected) {
					say("renoir-wifi: unexpected command completion %#llx expected %#llx\n",completed,renoir_bhi.command_expected);
					return false;
				}
				renoir_bhi.command_result=value;
			}
			if (type==0x40) { renoir_bhi.ee=value; }
			if ((type==0x40 && value==3) || (type==0x20 && value==255)) {
				say("renoir-wifi: fatal MHI event ring %u type %#x data %#x flags %#x\n",ring,type,data,flags);return false;
			}
			local+=16; if (local==base+length) { local=base; }
			wp+=16; if (wp==base+length) { wp=base; }
			renoir_bhi.event_rp[ring]=local;
			renoir_mhi_write64(context+36,wp);
			processed++;
		}
		if (processed) {
			__asm__ volatile("dsb sy" ::: "memory");
			renoir_mhi_write64(bar+renoir_bhi.event_db+ring*8,renoir_mhi_read64(context+36));
		}
	}
	return true;
}

/* Diagnostic start of the real IPCR channels; no RX/TX buffers queued yet.
 * Contexts/rings stay within the already mapped, noncached control arena. */
static bool
renoir_mhi_start_ipcr(vm_offset_t bar)
{
	if (renoir_bhi.ee!=2 && renoir_bhi.ee!=4) { return false; }
	uint64_t control=RADIO_ADDRESSES+renoir_bhi.control;
	for (unsigned channel=20;channel<=21;channel++) {
		vm_offset_t ctxt=renoir_bhi.control_alias+channel*44;
		uint64_t ring=control+(channel==20 ? 0xa000 : 0xb000);
		wr(ctxt+4,channel==20 ? 1 : 2); wr(ctxt+8,1);
		renoir_mhi_write64(ctxt+12,ring); renoir_mhi_write64(ctxt+20,32*16);
		renoir_mhi_write64(ctxt+28,ring); renoir_mhi_write64(ctxt+36,ring);
		wr(ctxt,0x201); /* enabled, burst doorbells disabled, OKX shima IPCR */
		unsigned slot=channel-20;
		vm_offset_t tre=renoir_bhi.control_alias+0x4000+slot*16;
		renoir_mhi_write64(tre,0); wr(tre+8,0); wr(tre+12,(channel<<24)|(18<<16));
		renoir_bhi.command_expected=control+0x4000+slot*16;
		renoir_bhi.command_result=0;
		renoir_mhi_write64(renoir_bhi.control_alias+0x3000+36,control+0x4000+(slot+1)*16);
		__asm__ volatile("dsb sy" ::: "memory");
		renoir_mhi_write64(bar+0x70,control+0x4000+(slot+1)*16);
		for (unsigned ms=0;ms<2000 && !renoir_bhi.command_result;ms++) {
			if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { return false; }
			if (!renoir_bhi.command_result) { sleep_ms(1); }
		}
		say("renoir-wifi: IPCR channel %u START completion %u context state %#x\n",channel,renoir_bhi.command_result,rd(ctxt));
		if (renoir_bhi.command_result!=1) { return false; }
	}
	renoir_bhi.command_expected=0;
	say("renoir-wifi: IPCR channels 20/21 started; no network interface yet\n");
	return true;
}

static bool
renoir_mhi_probe_ipcr(vm_offset_t bar)
{
	uint64_t control=RADIO_ADDRESSES+renoir_bhi.control;
	/* QRTR v1 HELLO: host node 1, control port, broadcast destination. */
	static const uint32_t hello[]={1,2,1,0xfffffffe,0,20,0xffffffff,0xfffffffe,2,0,0,0,0};
	vm_offset_t packet=renoir_bhi.control_alias+0xe000;
	for (unsigned word=0;word<sizeof(hello)/4;word++) { wr(packet+word*4,hello[word]); }
	renoir_mhi_post_rx(bar);
	vm_offset_t tre=renoir_bhi.control_alias+0xa000;
	renoir_mhi_write64(tre,control+0xe000); wr(tre+8,sizeof(hello)); wr(tre+12,0x20200);
	renoir_bhi.tx_expected=control+0xa000; renoir_bhi.tx_slot=1;
	renoir_mhi_write64(renoir_bhi.control_alias+20*44+36,control+0xa010);
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_mhi_write64(bar+renoir_bhi.channel_db+20*8,control+0xa010);
	for (unsigned ms=0;ms<3000;ms++) {
		if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { return false; }
		sleep_ms(1);
	}
	say("renoir-wifi: IPCR probe HELLO acknowledged %u received %u packets\n",renoir_bhi.tx_done,renoir_bhi.rx_packets);
	return renoir_bhi.tx_done && renoir_bhi.rx_packets;
}

static void
renoir_mhi_submit_tx(vm_offset_t bar, unsigned length)
{
	unsigned slot=renoir_bhi.tx_slot;uint64_t control=RADIO_ADDRESSES+renoir_bhi.control;
	vm_offset_t tre=renoir_bhi.control_alias+0xa000+slot*16;
	renoir_mhi_write64(tre,control+0xe000); wr(tre+8,length); wr(tre+12,0x20200);
	renoir_bhi.tx_expected=control+0xa000+slot*16; renoir_bhi.tx_done=false;
	renoir_bhi.tx_slot=(slot+1)%32;
	uint64_t next=control+0xa000+renoir_bhi.tx_slot*16;
	renoir_mhi_write64(renoir_bhi.control_alias+20*44+36,next);
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_mhi_write64(bar+renoir_bhi.channel_db+20*8,next);
}

static bool
renoir_mhi_resume_qrtr(vm_offset_t bar)
{
	if (!renoir_bhi.resume_pending) { return true; }
	if (!renoir_bhi.tx_done) { return false; }
	uint32_t resume[]={1,7,renoir_bhi.resume_local_node,renoir_bhi.resume_local_port,0,20,
	    renoir_bhi.resume_node,renoir_bhi.resume_port,7,renoir_bhi.resume_local_node,renoir_bhi.resume_local_port,0,0};
	vm_offset_t packet=renoir_bhi.control_alias+0xe000;
	for (unsigned word=0;word<13;word++) { wr(packet+word*4,resume[word]); }
	renoir_bhi.resume_pending=false;
	renoir_mhi_submit_tx(bar,sizeof(resume));
	for (unsigned ms=0;ms<2000 && !renoir_bhi.tx_done;ms++) {
		if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { return false; }
		if (!renoir_bhi.tx_done) { sleep_ms(1); }
	}
	return renoir_bhi.tx_done;
}

static bool
renoir_mhi_probe_qmi(vm_offset_t bar, unsigned message, const uint8_t *tlvs, unsigned length)
{
	if (!renoir_bhi.wlfw_node || !renoir_bhi.wlfw_port || !renoir_bhi.tx_done || length>1024 || (length && !tlvs)) { return false; }
	renoir_bhi.qmi_message=message; renoir_bhi.qmi_transaction++;
	renoir_bhi.reply_seen=false; renoir_bhi.reply_ok=false;
	uint32_t header[]={1,1,1,0x4000,0,7+length,renoir_bhi.wlfw_node,renoir_bhi.wlfw_port};
	uint8_t body[1032]={0};
	body[1]=renoir_bhi.qmi_transaction; body[2]=renoir_bhi.qmi_transaction>>8;
	body[3]=message; body[4]=message>>8; body[5]=length; body[6]=length>>8;
	if (length) { memcpy(body+7,tlvs,length); }
	vm_offset_t packet=renoir_bhi.control_alias+0xe000;
	for (unsigned word=0;word<8;word++) { wr(packet+word*4,header[word]); }
	unsigned payload=(7+length+3)&~3u;
	for (unsigned offset=0;offset<payload;offset+=4) {
		uint32_t value; memcpy(&value,body+offset,4); wr(packet+32+offset,value);
	}
	renoir_mhi_submit_tx(bar,32+payload);
	for (unsigned ms=0;ms<3000 && (!renoir_bhi.reply_seen || !renoir_bhi.tx_done);ms++) {
		if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) {
			say("renoir-wifi: QMI %#x aborted MHI %#x BHI EE %#x error %#x\n",message,rd(bar+0x48),rd(bar+renoir_bhi.bhi_offset+0x28),rd(bar+renoir_bhi.bhi_offset+0x30));return false;
		}
		if (!renoir_bhi.reply_seen || !renoir_bhi.tx_done) { sleep_ms(1); }
	}
	if (message!=0x25 || !renoir_bhi.reply_ok) { say("renoir-wifi: QMI probe message %#x TX %u reply %u success %u\n",message,renoir_bhi.tx_done,renoir_bhi.reply_seen,renoir_bhi.reply_ok); }
	return renoir_bhi.tx_done && renoir_bhi.reply_seen && renoir_bhi.reply_ok && renoir_mhi_resume_qrtr(bar);
}

static bool
renoir_mhi_download_board(vm_offset_t bar, const char *name, unsigned type)
{
	uint64_t size=0;const uint8_t *file=image_file_in("fw-wifi-renoir",name,&size);
	if (!file || !size || size>0x100000 || (type==1 && (size<4 || memcmp(file,"\177ELF",4)))) { return false; }
	for (unsigned offset=0,segment=0;offset<size;segment++) {
		unsigned count=size-offset>512 ? 512 : size-offset;
		uint8_t request[550];
		unsigned length=renoir_mhi_bdf_chunk(request,sizeof(request),file+offset,count,size-offset,segment,renoir_bhi.board_id,type);
		if (!length || !renoir_mhi_probe_qmi(bar,0x25,request,length)) {
			say("renoir-wifi: %s transfer failed at %u/%llu bytes\n",name,offset,size);return false;
		}
		offset+=count;
		if (segment%32==0) { say("renoir-wifi: %s %u/%llu bytes\n",name,offset,size); }
	}
	say("renoir-wifi: %s accepted (%llu bytes)\n",name,size);return true;
}

static bool
renoir_mhi_m3_info(vm_offset_t bar)
{
	uint64_t size=0;const uint8_t *file=image_file_in("fw-wifi-renoir","m3.bin",&size);
	if (!file || !size || size>0x100000) { return false; }
	uint64_t alignment=16384;while (alignment<size) { alignment<<=1; }
	uint64_t start=RADIO_ADDRESSES+renoir_bhi.control+0x10000+renoir_bhi.memory_used;
	uint64_t address=(start+alignment-1)&~(alignment-1), offset=address-RADIO_ADDRESSES;
	if (address<start || offset>renoir_bhi.allocation || size>renoir_bhi.allocation-offset) { return false; }
	vm_offset_t buffer=renoir_bhi.buffer+offset;
	memcpy((void *)buffer,file,size);
	for (vm_offset_t line=buffer;line<buffer+size;line+=64) {
		__asm__ volatile("dc civac, %0" : : "r"(line) : "memory");
	}
	__asm__ volatile("dsb sy" ::: "memory");
	uint8_t request[18]={1,8,0};
	for (unsigned byte=0;byte<8;byte++) { request[3+byte]=address>>(byte*8); }
	renoir_qmi_u32_tlv(request+11,2,size);
	if (!renoir_mhi_probe_qmi(bar,0x3c,request,sizeof(request))) { return false; }
	for (unsigned ms=0;ms<5000 && !renoir_bhi.firmware_ready;ms++) {
		if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { return false; }
		if (!renoir_bhi.firmware_ready) { sleep_ms(1); }
	}
	say("renoir-wifi: M3 accepted (%llu bytes at %#llx), firmware initialized %u\n",size,address,renoir_bhi.firmware_ready);
	return renoir_bhi.firmware_ready;
}

static bool
renoir_bhie_load(vm_offset_t bar)
{
	uint32_t channel_db=rd(bar+0x18), event_db=rd(bar+0x20), bhie_offset=rd(bar+0x2c), bhi_offset=rd(bar+0x28);
	if (!channel_db || (channel_db&7) || channel_db>0x10000-128*8 ||
	    !event_db || (event_db&7) || event_db>0x10000-16 ||
	    !bhie_offset || (bhie_offset&3) || bhie_offset>0x10000-0x80 ||
	    !bhi_offset || (bhi_offset&3) || bhi_offset>0x10000-0x2c ||
	    !(rd(bar+0x48)&1) || (rd(bar+0x38)&2)) {
		say("renoir-wifi: MHI READY/doorbell validation failed: CH %#x ER %#x BHIE %#x\n",channel_db,event_db,bhie_offset);
		return false;
	}
	struct renoir_mhi_layout layout;
	if (!renoir_mhi_make_layout((void *)renoir_bhi.buffer,renoir_bhi.firmware_size,
	    renoir_bhi.allocation,RADIO_ADDRESSES,&layout)) { return false; }
	for (vm_offset_t line=renoir_bhi.buffer+layout.control; line<renoir_bhi.buffer+renoir_bhi.allocation; line+=64) {
		__asm__ volatile("dc civac, %0" : : "r"(line) : "memory");
	}
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_bhi.control_alias=ml_io_map_unmappable(kvtophys(renoir_bhi.buffer)+layout.control,0x10000,VM_WIMG_WCOMB);
	if (!renoir_bhi.control_alias) { return false; }
	uint64_t expected_physical=kvtophys(renoir_bhi.buffer+layout.control);
	uint64_t alias_physical=kvtophys(renoir_bhi.control_alias);
	volatile struct renoir_mhi_context *alias_events=(void *)(renoir_bhi.control_alias+0x2000);
	struct renoir_mhi_context *cached_events=(void *)(renoir_bhi.buffer+layout.control+0x2000);
	say("renoir-wifi: MHI control physical %#llx alias physical %#llx cached RP %#llx alias RP %#llx\n",
	    expected_physical,alias_physical,cached_events[0].rp,renoir_mhi_read64((vm_offset_t)alias_events+28));
	if (alias_physical!=expected_physical || memcmp((void *)renoir_bhi.control_alias,
	    (void *)(renoir_bhi.buffer+layout.control),0x10000)) {
		say("renoir-wifi: MHI control alias mismatch; ring DMA not started\n");return false;
	}
	renoir_bhi.bhie_offset=bhie_offset;
	renoir_bhi.channel_db=channel_db;
	renoir_bhi.control=layout.control; renoir_bhi.event_db=event_db; renoir_bhi.ee=1;
	renoir_bhi.event_rp[0]=RADIO_ADDRESSES+layout.control+0x5000;
	renoir_bhi.event_rp[1]=RADIO_ADDRESSES+layout.control+0x6000;
	renoir_mhi_write64(bar+0x58,RADIO_ADDRESSES+layout.control);
	renoir_mhi_write64(bar+0x60,RADIO_ADDRESSES+layout.control+0x2000);
	renoir_mhi_write64(bar+0x68,RADIO_ADDRESSES+layout.control+0x3000);
	wr(bar+0x10,(rd(bar+0x10)&0xffff)|2u<<16); /* two software events, zero hardware events */
	renoir_mhi_write64(bar+0x80,RADIO_ADDRESSES);
	renoir_mhi_write64(bar+0x88,RADIO_ADDRESSES+renoir_bhi.allocation-1);
	renoir_mhi_write64(bar+0x98,RADIO_ADDRESSES);
	renoir_mhi_write64(bar+0xa0,RADIO_ADDRESSES+renoir_bhi.allocation-1);
	renoir_mhi_write64(bar+channel_db+127*8,0);
	renoir_mhi_write64(bar+event_db,RADIO_ADDRESSES+layout.control+0x5000+512-16);
	renoir_mhi_write64(bar+event_db+8,RADIO_ADDRESSES+layout.control+0x6000+4096-16);
	__asm__ volatile("dsb sy" ::: "memory");
	wr(bar+0x38,(rd(bar+0x38)&~0xff00u)|0x200); /* M0 */
	renoir_mhi_write64(bar+channel_db+127*8,1); /* keep awake during download */
	bool m0=false;
	for (unsigned ms=0; ms<2000; ms++) {
		if (!renoir_mhi_poll_boot_events(bar)) { return false; }
		uint32_t status=rd(bar+0x48);
		if (status&4) { break; }
		if ((status&0xff00)==0x200) { m0=true; break; }
		sleep_ms(1);
	}
	say("renoir-wifi: MHI M0 reached %u status %#x CHDB %#x ERDB %#x\n",m0,rd(bar+0x48),channel_db,event_db);
	if (!m0) { return false; }
	vm_offset_t bhie=bar+bhie_offset;
	renoir_mhi_write64(bhie+0x2c,RADIO_ADDRESSES+layout.vectors);
	wr(bhie+0x34,layout.vector_size);
	__asm__ volatile("dsb sy" ::: "memory");
	wr(bhie+0x3c,(rd(bhie+0x3c)&0xc0000000)|2);
	uint32_t status=0;
	for (unsigned ms=0; ms<5000; ms++) {
		if (!renoir_mhi_poll_boot_events(bar)) { return false; }
		status=rd(bhie+0x44);
		if (status>>30 || (rd(bar+0x48)&4)) { break; }
		sleep_ms(1);
	}
	uint32_t ee=renoir_bhi.ee;
	if (status>>30==2) {
		for (unsigned ms=0; ms<5000 && ee!=2 && ee!=4 && ee!=3; ms++) {
			if (!renoir_mhi_poll_boot_events(bar)) { return false; }
			ee=renoir_bhi.ee;
			uint32_t raw=rd(bar+bhi_offset+0x28);
			if (raw==2 || raw==4 || raw==3) { ee=raw; }
			if (ee!=2 && ee!=4 && ee!=3) { sleep_ms(1); }
		}
	}
	say("renoir-wifi: BHIE transfer status %#x EE %#x BHI EE %#x MHI status %#x (%u bytes, %u vectors)\n",
	    status,ee,rd(bar+bhi_offset+0x28),rd(bar+0x48),renoir_bhi.firmware_size,layout.vector_size/16);
	if (status>>30!=2 || (ee!=2 && ee!=4)) { return false; }
	renoir_bhi.ee=ee;
	return true;
}

static bool
renoir_bhi_load(vm_offset_t bar, vm_offset_t config, vm_offset_t dbi, unsigned probe)
{
	bool manual_calibration=probe==28;
	if (manual_calibration) { probe=26; }
	uint64_t size=0;
	const uint8_t *firmware=image_file_in("fw-wifi-renoir","amss20.bin",&size);
	uint32_t offset=rd(bar+0x28);
	if (!firmware || size<RENOIR_BHI_SIZE || size>0x800000 || memcmp(firmware,"\177ELF",4) ||
	    !offset || (offset&3) || offset>0x10000-0x40 || rd(bar+offset+0x28)!=0) {
		say("renoir-wifi: BHI firmware/state validation failed; DMA not enabled\n");return false;
	}
	renoir_bhi.target_extra=(probe>=23 && probe<=26) ? 0x2000000 : probe>=27 ? 0x800000 : 0;
	if (!renoir_bhi_prepare(firmware,(uint32_t)size,probe>=17)) {
		say("renoir-wifi: BHI DMA preparation failed; DMA not enabled\n");return false;
	}
	renoir_bhi.bhi_offset=offset;
	vm_offset_t bhi=bar+offset;
	uint32_t msi_header=rd(config+0x50);
	if (probe>=17 && ((msi_header&0xff)!=5 || (msi_header&0x1800000)!=0x1000000 || ((msi_header>>17)&7)<5)) {
		say("renoir-wifi: unsupported MSI capability; firmware DMA not started\n"); return false;
	}
	renoir_bhi.active=true; /* quiesce can reset the endpoint before the first DMA */
	uint32_t ep_cmd=rd(config+4)&0xffff, root_cmd=rd(dbi+4)&0xffff;
	wr(dbi+4,root_cmd|6); wr(config+4,ep_cmd|6);
	__asm__ volatile("dsb sy" ::: "memory");
	if ((rd(config+4)&6)!=6 || (rd(dbi+4)&6)!=6) {
		say("renoir-wifi: BHI bus mastering enable refused\n");
		wr(config+4,ep_cmd&~4u);wr(dbi+4,root_cmd);
		return false;
	}
	/* The firmware emits MSI even during polled bring-up. Give those writes
	 * an isolated, mapped RAM destination instead of an unprogrammed address.
	 * Probes 17+ only: this is a notification sink, not an interrupt driver. */
	uint32_t msi[4]={0}; bool msi_sink=false;
	if (probe>=17 && (rd(config+0x50)&0xff)==5 && (rd(config+0x50)&0x1800000)==0x1000000) {
		for (unsigned i=0;i<4;i++) { msi[i]=rd(config+0x50+4*i); }
		wr(config+0x50,msi[0]&~0x10000u);
		wr(config+0x54,(uint32_t)(RADIO_ADDRESSES+round_page(renoir_bhi.firmware_size)+0x9000));
		wr(config+0x58,0); wr(config+0x5c,0);
		wr(config+0x50,(msi[0]&~0x710000u)|0x510000u);
		if (rd(config+0x54)!=(uint32_t)(RADIO_ADDRESSES+round_page(renoir_bhi.firmware_size)+0x9000) ||
		    (rd(config+0x50)&0x710000)!=0x510000 || rd(config+0x58) || rd(config+0x5c)) {
			wr(config+0x50,rd(config+0x50)&~0x10000u);
			wr(config+4,ep_cmd&~4u); wr(dbi+4,root_cmd);
			for (unsigned i=1;i<4;i++) { wr(config+0x50+4*i,msi[i]); }
			wr(config+0x50,msi[0]);
			say("renoir-wifi: MSI setup refused; firmware DMA not started\n"); return false;
		}
		msi_sink=true;
		say("renoir-wifi: probe MSI sink address %#x control %#x\n",rd(config+0x54),rd(config+0x50));
	}
	wr(bhi+0x2c,0); wr(bhi+0x0c,0); wr(bhi+8,(uint32_t)RADIO_ADDRESSES);
	wr(bhi+0x10,RENOIR_BHI_SIZE);
	__asm__ volatile("dsb sy" ::: "memory");
	wr(bhi+0x18,1);
	uint32_t status=0;
	for (unsigned ms=0; ms<2000; ms++) {
		status=rd(bhi+0x2c);
		if (status>>30) { break; }
		sleep_ms(1);
	}
	/* Transfer completion precedes authentication / the SBL hand-off. */
	if (status>>30==2) {
		for (unsigned ms=0; ms<2000 && rd(bhi+0x28)==0; ms++) { sleep_ms(1); }
	}
	status=rd(bhi+0x2c);
	say("renoir-wifi: BHI transfer status %#x EE %#x MHI status %#x error %#x debug %#x %#x %#x\n",
	    status,rd(bhi+0x28),rd(bar+0x48),rd(bhi+0x30),rd(bhi+0x34),rd(bhi+0x38),rd(bhi+0x3c));
	bool loaded=status>>30==2 && rd(bhi+0x28)==1;
	if (loaded && probe>=17) { loaded=renoir_bhie_load(bar); }
	if (loaded && probe>=18) { loaded=renoir_mhi_start_ipcr(bar); }
	if (loaded && (probe>=19 && probe<=26)) { loaded=renoir_mhi_probe_ipcr(bar); }
	if (loaded && probe==20) { loaded=renoir_mhi_probe_qmi(bar,0x24,NULL,0); }
	if (loaded && (probe>=21 && probe<=26)) {
		/* ath11k_qmi_fw_ind_register_send: FW_READY, client K N E L,
		 * REQUEST_MEM, FW_MEM_READY and FW_INIT_DONE indications. */
		static const uint8_t indications[]={0x10,1,0,1, 0x15,4,0,0x4c,0x45,0x4e,0x4b,
		    0x16,1,0,1, 0x17,1,0,1, 0x18,1,0,1};
		loaded=renoir_mhi_probe_qmi(bar,0x20,indications,sizeof(indications));
	}
	if (loaded && (probe>=22 && probe<=26)) {
		static const uint8_t host_cap[]={0x10,4,0,1,0,0,0, 0x14,1,0,1, 0x16,1,0,1,
		    0x17,1,0,1, 0x1a,1,0,0, 0x1c,1,0,0};
		loaded=renoir_mhi_probe_qmi(bar,0x34,host_cap,sizeof(host_cap));
		for (unsigned ms=0;loaded && ms<2000 && !renoir_bhi.memory_count;ms++) {
			if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { loaded=false;break; }
			if (!renoir_bhi.memory_count) { sleep_ms(1); }
		}
		say("renoir-wifi: QMI host capability success %u memory request segments %u (not allocated)\n",loaded,renoir_bhi.memory_count);
	}
	if (loaded && (probe>=23 && probe<=26)) {
		uint8_t reply[4+17*52]; uint32_t used=0;
		uint32_t start=renoir_bhi.control+0x10000;
		unsigned length=renoir_mhi_memory_reply(reply,sizeof(reply),renoir_bhi.memory_sizes,
		    renoir_bhi.memory_types,renoir_bhi.memory_count,RADIO_ADDRESSES+start,
		    renoir_bhi.allocation-start,&used);
		say("renoir-wifi: memory aperture CTRL %#llx..%#llx DATA %#llx..%#llx\n",
		    renoir_mhi_read64(bar+0x80),renoir_mhi_read64(bar+0x88),renoir_mhi_read64(bar+0x98),renoir_mhi_read64(bar+0xa0));
		renoir_bhi.memory_used=used;
		loaded=length && renoir_mhi_probe_qmi(bar,0x36,reply,length);
		for (unsigned ms=0;loaded && ms<3000 && !renoir_bhi.memory_ready;ms++) {
			if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) { loaded=false;break; }
			if (!renoir_bhi.memory_ready) { sleep_ms(1); }
		}
		say("renoir-wifi: QMI memory response success %u FW_MEM_READY %u %u KiB at %#llx\n",loaded,renoir_bhi.memory_ready,used/1024,RADIO_ADDRESSES+start);
		loaded=loaded && renoir_bhi.memory_ready;
	}
	if (!loaded) { say("renoir-wifi: failed stage %u MHI %#x BHI EE %#x root link %#x\n",probe,rd(bar+0x48),rd(bhi+0x28),rd(dbi+0x80)); }
	if (loaded && (probe>=24 && probe<=26)) { loaded=renoir_mhi_probe_qmi(bar,0x24,NULL,0); }
	if (loaded && (probe>=25 && probe<=26)) { loaded=renoir_mhi_download_board(bar,"regdb.bin",4) && renoir_mhi_download_board(bar,"bd_k9gl.elf",1); }
	if (loaded && (probe>=26 && probe<=26)) { loaded=renoir_mhi_m3_info(bar); }
	if (loaded && manual_calibration) {
		static const uint8_t grant[]={0x10,8,0,0,0,0,0,0,0,0,0};
		loaded=renoir_mhi_probe_qmi(bar,0x47,NULL,0) && renoir_mhi_probe_qmi(bar,0x48,grant,sizeof(grant));
		say("renoir-wifi: calibration antenna switch/grant accepted %u\n",loaded);
	}
	if (loaded && manual_calibration) {
		static const uint8_t mode[]={1,4,0,7,0,0,0,0x10,1,0,0};
		loaded=renoir_mhi_probe_qmi(bar,0x22,mode,sizeof(mode));
		say("renoir-wifi: manual cold calibration request accepted %u\n",loaded);
		for (unsigned ms=0;loaded && ms<10000;ms++) {
			if (!renoir_mhi_poll_boot_events(bar) || (rd(bar+0x48)&4)) {
				say("renoir-wifi: manual calibration failed MHI %#x EE %#x error %#x\n",rd(bar+0x48),rd(bhi+0x28),rd(bhi+0x30));loaded=false;break;
			}
			sleep_ms(1);
		}
	}
	if (loaded && probe>=27) { loaded=renoir_mhi_runtime(bar); }
	radio_space_faults();
	if (msi_sink) { wr(config+0x50,rd(config+0x50)&~0x10000u); }
	wr(config+4,ep_cmd&~4u);wr(dbi+4,root_cmd);
	__asm__ volatile("dsb sy" ::: "memory");
	sleep_us(100);
	if (msi_sink) {
		for (unsigned i=1;i<4;i++) { wr(config+0x50+4*i,msi[i]); }
		wr(config+0x50,msi[0]);
	}
	return loaded;
}
