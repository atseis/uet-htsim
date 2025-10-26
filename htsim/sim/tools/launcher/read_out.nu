open out.txt 
	| lines 
	| parse "Running permutation with global parameters: {global} and subparameters: {sub}"  
	| update global { |g | $g.global |  from yaml } 
	| update sub { |g | $g.sub |  from yaml } 
	| each { |row | $row | merge $row.global | reject global}
	| each { |row | $row | merge $row.sub | reject sub}
    # | group-by --to-table link_speed_Gbps  oversubscription_ratio  topology_sizes   cc_algo 
