removable_dev ()
{
	output_format="${1}"
	want_usb="${2}"
	ret=

	for sysblock in $(echo /sys/block/* | tr ' ' '\n' | grep -vE "/(loop|ram|dm-|fd)")
	do
		if [ ! -d "${sysblock}" ]; then
			continue
		fi

		dev_ok=
		if [ "$(cat ${sysblock}/removable)" = "1" ]
		then
			if [ -z "${want_usb}" ]
			then
				dev_ok="true"
			else
				if readlink ${sysblock} | grep -q usb
				then
					dev_ok="true"
				fi
			fi
		fi

		if [ "${dev_ok}" = "true" ]
		then
			case "${output_format}" in
				sys)
					ret="${ret} ${sysblock}"
					;;
				*)
					devname=$(sys2dev "${sysblock}")
					ret="${ret} ${devname}"
					;;
			esac
		fi
	done

	echo "${ret}"
}

removable_usb_dev ()
{
	output_format="${1}"

	removable_dev "${output_format}" "want_usb"
}

non_removable_dev ()
{
	output_format="${1}"
	ret=

	for sysblock in $(echo /sys/block/* | tr ' ' '\n' | grep -vE "/(loop|ram|dm-|fd)")
	do
		if [ ! -d "${sysblock}" ]; then
			continue
		fi

		if [ "$(cat ${sysblock}/removable)" = "0" ]
		then
			case "${output_format}" in
				sys)
					ret="${ret} ${sysblock}"
					;;
				*)
					devname=$(sys2dev "${sysblock}")
					ret="${ret} ${devname}"
					;;
			esac
		fi
	done

	echo "${ret}"
}
