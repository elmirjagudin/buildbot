define(["jquery","realtimePages","helpers","dataTables","handlebars","extend-moment","libs/jquery.form","text!templates/builderdetail.handlebars","timeElements","rtGenericTable","popup"],function(e,t,n,r,i,s,o,u,a,f,l){var c,h,p,d,v,m=Handlebars.compile(u);return c={init:function(){h=c.currentBuildsTableInit(e("#rtCurrentBuildsTable")),p=c.pendingBuildsTableInit(e("#rtPendingBuildsTable")),d=f.table.buildTableInit(e("#rtBuildsTable")),v=c.slavesTableInit(e("#rtSlavesTable"));var r=t.defaultRealtimeFunctions();r.project=c.rtfProcessCurrentBuilds,r.pending_builds=c.rtfProcessPendingBuilds,r.builds=c.rtfProcessBuilds,r.slaves=c.rtfProcessSlaves,l.registerJSONPopup(v),t.initRealtime(r),n.selectBuildsAction(p),window.location.search!==""&&n.codeBaseBranchOverview(e("#brancOverViewCont"))},rtfProcessCurrentBuilds:function(e){a.clearTimeObjects(h),h.fnClearTable();try{e.currentBuilds!==undefined&&(h.fnAddData(e.currentBuilds),a.updateTimeObjects()),a.updateTimeObjects()}catch(t){}},rtfProcessPendingBuilds:function(e){f.table.rtfGenericTableProcess(p,e)},rtfProcessSlaves:function(e){e=n.objectPropertiesToArray(e),f.table.rtfGenericTableProcess(v,e)},rtfProcessBuilds:function(e){f.table.rtfGenericTableProcess(d,e)},currentBuildsTableInit:function(t){var n={};return n.oLanguage={sEmptyTable:"No current builds"},n.aoColumns=[{mData:null,sTitle:"#",sWidth:"10%"},{mData:null,sTitle:"Current build",sWidth:"30%"},{mData:null,sTitle:"Revision",sWidth:"40%"},{mData:null,sTitle:"Author",sWidth:"20%",sClass:"txt-align-right"}],n.aoColumnDefs=[f.cell.buildID(0),f.cell.buildProgress(1,!0),f.cell.revision(2,"sourceStamps"),{aTargets:[3],sClass:"txt-align-left",mRender:function(t,n,r){var i="N/A";return r.properties!==undefined&&e.each(r.properties,function(e,t){t[0]==="owner"&&(i=t[1])}),i}}],r.initTable(t,n)},pendingBuildsTableInit:function(t){var n={};return n.oLanguage={sEmptyTable:"No pending builds"},n.aoColumns=[{mData:null,sWidth:"30%"},{mData:null,sWidth:"30%"},{mData:null,sWidth:"35%"},{mData:null,sWidth:"5%"}],n.aoColumnDefs=[{aTargets:[0],sClass:"txt-align-left",mRender:function(e,t,n){return s.getDateFormatted(n.submittedAt)}},{aTargets:[1],sClass:"txt-align-left",mRender:function(){return m({pendingBuildWait:!0})},fnCreatedCell:function(t,n,r){a.addElapsedElem(e(t).find(".waiting-time-js"),r.submittedAt)}},f.cell.revision(2,"sources"),{aTargets:[3],sClass:"txt-align-right",mRender:function(e,t,n){return m({removeBuildSelector:!0,data:n})}}],r.initTable(t,n)},slavesTableInit:function(e){var t={};return t.oLanguage={sEmptyTable:"No slaves attached"},t.aoColumns=[{mData:null,sWidth:"50%"},{mData:null,sWidth:"50%"}],t.aoColumnDefs=[f.cell.slaveName(0,"friendly_name","url"),f.cell.slaveStatus(1)],r.initTable(e,t)}},c});